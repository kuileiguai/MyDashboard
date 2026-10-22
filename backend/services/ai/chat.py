"""AI 对话主流程：模型 → 工具 → 模型，动作只提议不执行。"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator

import config
from services.ai import actions, catalog, context, store, tools
from services.ai.providers import ProviderError, get_active_provider
from services.ai.schemas import ChatRequest

_locks: dict[int, asyncio.Lock] = {}


def _lock(cid: int) -> asyncio.Lock:
    if cid not in _locks:
        _locks[cid] = asyncio.Lock()
    return _locks[cid]


def _usage_counts(usage: dict | None) -> tuple[int, int]:
    usage = usage or {}
    tin = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    tout = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return tin, tout


def _title_from_message(message: str) -> str:
    text = " ".join((message or "").strip().split())
    return text[:30] or "新对话"


async def _get_or_create(req: ChatRequest) -> dict:
    if req.conversation_id:
        conv = await store.get_conversation(req.conversation_id)
        if not conv:
            raise ValueError("会话不存在")
        return conv
    return await store.create_conversation(
        title=_title_from_message(req.message),
        project_id=(req.context or {}).get("project_id"),
        model=req.model or config.AI_MODEL,
        context=req.context or {},
    )


async def chat_stream(req: ChatRequest) -> AsyncIterator[dict]:
    if not config.AI_ENABLED:
        yield {"type": "error", "code": "disabled", "message": "AI 功能未启用（DASH_AI_ENABLED=0）"}
        return

    message = (req.message or "").strip()
    if not message:
        yield {"type": "error", "code": "empty_message", "message": "消息不能为空"}
        return

    try:
        conv = await _get_or_create(req)
    except ValueError as e:
        yield {"type": "error", "code": "conversation_not_found", "message": str(e)}
        return

    cid = int(conv["id"])
    run_id = uuid.uuid4().hex[:12]

    async with _lock(cid):
        # 历史要在写入本轮 user 消息之前取
        history_records = await store.list_messages(cid, 40)
        history = context.messages_from_history(history_records)

        try:
            overview = await catalog.catalog_overview(include_env=False, compact=True)
        except Exception:
            overview = {"counts": {}, "note": "配置总览暂不可用，请用工具按需查询。"}

        system = context.build_system_prompt(overview)
        user = {"role": "user", "content": context.build_user_content(message, req.context)}
        messages = context.trim_messages(
            [system, *history, user],
            max(4000, config.AI_CONTEXT_BUDGET - config.AI_MAX_TOKENS),
        )

        user_msg_id = await store.add_message(cid, "user", message)
        if not (conv.get("title") or "").strip():
            await store.touch_conversation(cid, _title_from_message(message))

        yield {
            "type": "start",
            "conversation_id": cid,
            "message_id": user_msg_id,
            "run_id": run_id,
        }

        full_text = ""
        total_in = 0
        total_out = 0
        estimated_any = False

        try:
            provider = await get_active_provider(req.model)
        except ProviderError as e:
            yield {"type": "error", "code": e.code, "message": e.message}
            return
        except Exception as e:
            yield {"type": "error", "code": "provider_error", "message": str(e)}
            return

        supports_tools = bool(getattr(getattr(provider, "cfg", None), "supports_tools", True))
        tool_specs = tools.TOOLS if supports_tools else None

        for _round in range(max(1, config.AI_MAX_TOOL_ROUNDS)):
            round_text = ""
            tool_calls: list[dict] = []
            usage: dict = {}

            try:
                async for ev in provider.stream_chat(messages, tools=tool_specs):
                    if ev.get("type") == "token":
                        delta = ev.get("delta") or ""
                        if delta:
                            round_text += delta
                            full_text += delta
                            yield {"type": "token", "delta": delta}
                    elif ev.get("type") == "end":
                        tool_calls = ev.get("tool_calls") or []
                        usage = ev.get("usage") or {}
            except ProviderError as e:
                if full_text:
                    await store.add_message(cid, "assistant", full_text,
                                            tokens_in=total_in, tokens_out=total_out,
                                            tokens_estimated=estimated_any)
                yield {"type": "error", "code": e.code, "message": e.message}
                return
            except asyncio.CancelledError:
                if full_text:
                    try:
                        await store.add_message(cid, "assistant", full_text,
                                                tokens_in=total_in, tokens_out=total_out,
                                                tokens_estimated=estimated_any)
                    except Exception:
                        pass
                raise
            except Exception as e:
                yield {"type": "error", "code": "chat_error", "message": str(e)}
                return

            tin, tout = _usage_counts(usage)
            estimated = False
            if tin == 0:
                tin = _estimate_input_tokens(messages)
                estimated = True
            if tout == 0 and (round_text or tool_calls):
                tout = _estimate_output_tokens(round_text, tool_calls)
                estimated = True
            if estimated:
                estimated_any = True
            total_in += tin
            total_out += tout

            if not tool_calls:
                if not full_text.strip():
                    full_text = "（模型没有返回内容）"
                await store.add_message(cid, "assistant", full_text,
                                        tokens_in=total_in, tokens_out=total_out,
                                        tokens_estimated=estimated_any)
                conv_usage = await store.conversation_usage(cid)
                yield {
                    "type": "done",
                    "usage": {"in": total_in, "out": total_out, "estimated": estimated_any},
                    "conversation_usage": conv_usage,
                }
                return

            action_calls = [c for c in tool_calls if actions.is_action_tool(_name(c))]
            read_calls = [c for c in tool_calls if not actions.is_action_tool(_name(c))]

            if len(action_calls) > 1:
                await store.add_message(cid, "assistant",
                                        full_text or "一次只能提议一个动作。",
                                        tokens_in=total_in, tokens_out=total_out,
                                        tokens_estimated=estimated_any)
                yield {"type": "error", "code": "too_many_actions",
                       "message": "一次只能提议一个动作，请分开询问。"}
                return

            read_results: list[tuple[dict, dict]] = []
            for call in read_calls:
                name = _name(call)
                args = tools.parse_tool_args((call.get("function") or {}).get("arguments"))
                result, duration = await tools.timed_read_tool(name, args)
                await store.record_tool_call(
                    cid, None, name, args, result,
                    "ok" if result.get("ok") else "error", duration)
                read_results.append((call, result))
                yield {"type": "tool_result", "id": call.get("id"), "name": name,
                       "ok": bool(result.get("ok")), "data": result,
                       "truncated": bool(result.get("truncated"))}

            if read_results:
                messages.append({
                    "role": "assistant",
                    "content": round_text or None,
                    "tool_calls": [_tool_call_payload(c) for c, _ in read_results],
                })
                for call, result in read_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id") or "",
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })

            if action_calls:
                call = action_calls[0]
                name = _name(call)
                args = tools.parse_tool_args((call.get("function") or {}).get("arguments"))
                try:
                    action = await actions.propose(cid, None, name, args)
                except actions.ActionError as e:
                    await store.add_message(cid, "assistant", f"动作未生成：{e.message}")
                    yield {"type": "error", "code": e.code, "message": e.message}
                    return

                assistant_text = full_text.strip() or "已生成待确认动作，请确认后执行。"
                msg_id = await store.add_message(
                    cid, "assistant", assistant_text,
                    tokens_in=total_in, tokens_out=total_out,
                    tokens_estimated=estimated_any)
                await store.set_action_message_id(action["action_id"], msg_id)
                conv_usage = await store.conversation_usage(cid)
                yield {"type": "action_proposed", **action, "message": msg_id}
                yield {
                    "type": "done",
                    "usage": {"in": total_in, "out": total_out, "estimated": estimated_any},
                    "conversation_usage": conv_usage,
                }
                return

            # 还有下一轮：继续让模型基于工具结果回答

        # 达到工具轮数上限
        if not full_text.strip():
            full_text = "已达到工具调用上限，请把问题拆小一点再问。"
        await store.add_message(cid, "assistant", full_text,
                                tokens_in=total_in, tokens_out=total_out,
                                tokens_estimated=estimated_any)
        conv_usage = await store.conversation_usage(cid)
        yield {
            "type": "done",
            "usage": {"in": total_in, "out": total_out, "estimated": estimated_any},
            "conversation_usage": conv_usage,
            "note": "max_tool_rounds",
        }


def _name(call: dict) -> str:
    return str(((call.get("function") or {}).get("name")) or "")


def _estimate_input_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        total += context.estimate_tokens(str(m.get("content") or ""))
        for tc in m.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            total += context.estimate_tokens(str(fn.get("name") or ""))
            total += context.estimate_tokens(str(fn.get("arguments") or ""))
    return max(1, total)


def _estimate_output_tokens(text: str, tool_calls: list[dict] | None = None) -> int:
    raw = text or ""
    if tool_calls:
        raw += json.dumps(tool_calls, ensure_ascii=False)
    return max(1, context.estimate_tokens(raw))


def _tool_call_payload(call: dict) -> dict:
    fn = call.get("function") or {}
    return {
        "id": call.get("id") or "",
        "type": "function",
        "function": {
            "name": fn.get("name") or "",
            "arguments": fn.get("arguments") or "{}",
        },
    }


async def conversation_detail(cid: int) -> dict | None:
    conv = await store.get_conversation(cid)
    if not conv:
        return None
    messages = await store.list_messages(cid, 500)
    acts = await store.list_actions(cid, 200)
    usage = await store.conversation_usage(cid)
    return {**conv, "messages": messages, "actions": acts, "usage": usage}
