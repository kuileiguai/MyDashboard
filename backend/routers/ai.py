"""M11 AI 对话路由。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import config
from database import get_db
from services.ai import actions, catalog, chat, providers, store, tools
from services.ai.schemas import ChatRequest, ConversationCreate, ConversationPatch, ProviderIn
from services.ssh_secret import encrypt_secret

router = APIRouter()


# ── 配置 / 健康检查 ──────────────────────────────────────────────

def _masked_config(row: dict | None) -> dict:
    if row:
        try:
            extra = json.loads(row.get("extra_json") or "{}")
        except Exception:
            extra = {}
        return {
            "source": "db",
            "name": row.get("name") or "default",
            "kind": row.get("kind") or "openai-compatible",
            "base_url": row.get("base_url") or "",
            "model": row.get("model") or "",
            "has_key": bool(row.get("api_key_enc")),
            "enabled": bool(row.get("enabled")),
            "is_default": bool(row.get("is_default")),
            "timeout": extra.get("timeout", config.AI_TIMEOUT),
            "supports_tools": bool(extra.get("supports_tools", True)),
            "allow_cloud": config.AI_ALLOW_CLOUD,
            "action_mode": config.AI_ACTION_MODE,
        }
    return {
        "source": "env",
        "name": "default",
        "kind": config.AI_PROVIDER,
        "base_url": config.AI_BASE_URL,
        "model": config.AI_MODEL,
        "has_key": bool(config.AI_API_KEY),
        "enabled": config.AI_ENABLED,
        "is_default": True,
        "timeout": config.AI_TIMEOUT,
        "supports_tools": True,
        "allow_cloud": config.AI_ALLOW_CLOUD,
        "action_mode": config.AI_ACTION_MODE,
    }


async def _load_provider_row() -> dict | None:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM ai_providers ORDER BY is_default DESC, id ASC LIMIT 1")
    return dict(rows[0]) if rows else None


@router.get("/health")
async def ai_health(force: bool = False):
    return {
        "config": _masked_config(await _load_provider_row()),
        "health": await providers.health(force=force),
    }


@router.get("/config")
async def get_config():
    return _masked_config(await _load_provider_row())


@router.put("/config")
async def save_config(body: ProviderIn):
    kind = (body.kind or "openai-compatible").strip()
    if kind not in ("openai-compatible", "mock"):
        raise HTTPException(400, "kind 目前只支持 openai-compatible / mock")

    base_url = (body.base_url or "").strip().rstrip("/")
    model = (body.model or "").strip()
    if kind != "mock":
        if not base_url or not model:
            raise HTTPException(400, "base_url 和 model 不能为空")
        if not config.AI_ALLOW_CLOUD and not providers.is_private_url(base_url):
            raise HTTPException(
                400,
                "当前只允许本机/内网模型地址；如需公网模型请设置 DASH_AI_ALLOW_CLOUD=1",
            )

    row = await _load_provider_row()
    old_key = row.get("api_key_enc") if row else ""
    if body.api_key is None:
        key_enc = old_key or ""
    elif body.api_key.strip():
        key_enc = encrypt_secret(body.api_key.strip())
    else:
        key_enc = ""

    extra = {
        "supports_tools": bool(body.supports_tools),
        "timeout": float(body.timeout or config.AI_TIMEOUT),
    }

    async with get_db() as db:
        await db.execute("UPDATE ai_providers SET is_default = 0")
        if row:
            await db.execute(
                "UPDATE ai_providers SET name=?, kind=?, base_url=?, model=?, "
                "api_key_enc=?, enabled=?, is_default=1, extra_json=? WHERE id=?",
                (body.name or "default", kind, base_url, model, key_enc,
                 1 if body.enabled else 0, json.dumps(extra, ensure_ascii=False), row["id"]),
            )
        else:
            await db.execute(
                "INSERT INTO ai_providers "
                "(name, kind, base_url, model, api_key_enc, enabled, is_default, extra_json) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (body.name or "default", kind, base_url, model, key_enc,
                 1 if body.enabled else 0, 1, json.dumps(extra, ensure_ascii=False)),
            )
        await db.commit()

    providers.invalidate_health()
    return _masked_config(await _load_provider_row())


@router.post("/config/test")
async def test_config():
    return await providers.health(force=True)


# ── 会话 ─────────────────────────────────────────────────────────

@router.get("/conversations")
async def list_conversations(limit: int = Query(50, ge=1, le=200)):
    return await store.list_conversations(limit)


@router.post("/conversations")
async def create_conversation(body: ConversationCreate):
    conv = await store.create_conversation(
        title=(body.title or "").strip()[:120],
        project_id=body.project_id,
        model=config.AI_MODEL,
    )
    return conv


@router.get("/conversations/{cid}")
async def get_conversation(cid: int):
    detail = await chat.conversation_detail(cid)
    if not detail:
        raise HTTPException(404, "会话不存在")
    return detail


@router.patch("/conversations/{cid}")
async def patch_conversation(cid: int, body: ConversationPatch):
    ok = await store.update_conversation(cid, title=body.title, archived=body.archived)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return await store.get_conversation(cid)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: int):
    ok = await store.delete_conversation(cid)
    if not ok:
        raise HTTPException(404, "会话不存在")
    return {"ok": True}


# ── 配置百科 ─────────────────────────────────────────────────────

@router.get("/catalog")
async def get_catalog(types: str = "", include_env: bool = False):
    selected = [t.strip() for t in types.split(",") if t.strip()] or None
    try:
        return await catalog.catalog_overview(types=selected, include_env=include_env)
    except Exception as e:
        raise HTTPException(500, f"读取配置失败: {e}")


@router.get("/catalog/{item_type}/{item_id:path}")
async def get_catalog_detail(item_type: str, item_id: str):
    try:
        return await catalog.catalog_detail(item_type, item_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"读取配置详情失败: {e}")


# ── 对话流 ───────────────────────────────────────────────────────

@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def gen():
        async for event in chat.chat_stream(req):
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── 动作确认 / 审计 ──────────────────────────────────────────────

def _http_action_error(e: actions.ActionError):
    return HTTPException(e.status, detail={"code": e.code, "message": e.message})


@router.get("/actions")
async def list_actions(conversation_id: int | None = None, limit: int = Query(100, ge=1, le=500)):
    return await actions.list_actions(conversation_id, limit)


@router.post("/actions/{aid}/confirm")
async def confirm_action(aid: int, request: Request):
    confirmed_by = request.client.host if request.client else "local"
    try:
        result = await actions.confirm(aid, confirmed_by=confirmed_by)
    except actions.ActionError as e:
        # 执行失败也把结果写回会话，方便前端刷新后仍能看到
        row = await store.get_action(aid)
        if row:
            await store.add_message(
                int(row["conversation_id"]), "assistant",
                f"动作失败：{row.get('target_name')} {row.get('action')}（{e.message}）",
            )
        raise _http_action_error(e)

    summary = (
        f"动作结果：{result.get('target_name')} {result.get('action')}，"
        f"{result.get('before_status')} → {result.get('after_status')}。"
        f"{(result.get('result') or {}).get('message', '')}"
    ).strip()
    await store.add_message(int(result["conversation_id"]), "assistant", summary)
    return result


@router.post("/actions/{aid}/reject")
async def reject_action(aid: int, request: Request):
    confirmed_by = request.client.host if request.client else "local"
    try:
        result = await actions.reject(aid, confirmed_by=confirmed_by)
    except actions.ActionError as e:
        raise _http_action_error(e)
    await store.add_message(
        int(result["conversation_id"]), "assistant",
        f"已取消动作：{result.get('target_name')} {result.get('action')}。",
    )
    return result


# ── 调试 ─────────────────────────────────────────────────────────

@router.get("/tools")
async def list_tools():
    return [{
        "name": t["function"]["name"],
        "description": t["function"].get("description", ""),
        "parameters": t["function"].get("parameters", {}),
        "action": actions.is_action_tool(t["function"]["name"]),
    } for t in tools.TOOLS]
