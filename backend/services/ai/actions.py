"""白名单动作：提议 → 用户确认 → 执行 → 前后状态 → 审计。

模型只能输出 {target_type, target_id, action}；本模块负责：
- 目标必须真实存在；
- 动作必须在白名单；
- 状态必须允许；
- 执行前原子占用，防止重复点击；
- 执行后重新查状态。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import config
from database import get_db
from services.ai import catalog, store
from services.docker_service import compose_action, container_action, list_containers
from services.external_terminal import open_terminal_at

ACTION_WHITELIST: dict[str, set[str]] = {
    "service": {"start", "stop", "restart"},
    "docker_container": {"start", "stop", "restart"},
    "docker_compose": {"up", "stop", "restart"},
    "favorite_terminal": {"open"},
}

TOOL_TARGET = {
    "service_action": "service",
    "docker_container_action": "docker_container",
    "docker_compose_action": "docker_compose",
    "open_favorite_terminal": "favorite_terminal",
}


class ActionError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def is_action_tool(name: str) -> bool:
    return name in TOOL_TARGET


def _parse_created_at(raw: str) -> float | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(raw[:19], fmt).replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            continue
    return None


def _status_from_container(c: dict) -> str:
    state = str(c.get("state") or "").lower()
    status = str(c.get("status") or "").lower()
    if state == "running" or status.startswith("up"):
        return "running"
    if state in ("exited", "created", "dead") or status.startswith("exited"):
        return "stopped"
    return state or "unknown"


async def _compose_status(path: str) -> str:
    try:
        res = await asyncio.to_thread(compose_action, path, "ps")
        out = str(res.get("output") or "")
        if "Up " in out or "running" in out.lower():
            return "running"
        if out.strip():
            return "stopped"
        return "unknown"
    except Exception:
        return "unknown"


async def _find_container(container_id: str) -> dict:
    info = await catalog.docker_info(force=True)
    if not info.get("available"):
        raise ActionError("docker_unavailable", info.get("error") or "Docker 不可用")
    for c in info.get("containers") or []:
        cid = str(c.get("id") or "")
        name = str(c.get("name") or "")
        if cid == container_id or cid.startswith(container_id) or name == container_id:
            return c
    raise ActionError("target_not_found", f"容器不存在：{container_id}")


async def _resolve_target(target_type: str, target_id: str) -> dict:
    if target_type == "service":
        try:
            # 确认动作时以实时状态为准，避免 5s 缓存导致误判
            catalog.invalidate_service_cache()
            svc = await catalog.service_detail(int(target_id))
        except Exception:
            raise ActionError("target_not_found", f"服务不存在：{target_id}")
        return {
            "name": svc.get("name") or f"服务 #{target_id}",
            "before_status": svc.get("live_status") or "unknown",
            "data": svc,
        }

    if target_type == "docker_container":
        c = await _find_container(target_id)
        return {
            "name": c.get("name") or c.get("id") or target_id,
            "before_status": _status_from_container(c),
            "data": c,
        }

    if target_type == "docker_compose":
        info = await catalog.docker_info(force=True)
        for p in info.get("compose") or []:
            if p.get("path") == target_id or p.get("name") == target_id:
                if not p.get("exists"):
                    raise ActionError("target_not_found", f"Compose 文件不存在：{p.get('path')}")
                return {
                    "name": p.get("name") or target_id,
                    "before_status": await _compose_status(p.get("path") or target_id),
                    "data": p,
                }
        raise ActionError("target_not_found", f"Compose 项目未登记：{target_id}")

    if target_type == "favorite_terminal":
        for t in await catalog.favorite_terminals():
            if str(t.get("id")) == str(target_id):
                return {"name": t.get("name") or t.get("path") or target_id,
                        "before_status": "available", "data": t}
        raise ActionError("target_not_found", f"常用终端不存在：{target_id}")

    raise ActionError("invalid_target", f"不支持的目标类型：{target_type}")


async def propose(conversation_id: int, message_id: int | None, tool_name: str,
                  args: dict) -> dict:
    target_type = TOOL_TARGET.get(tool_name)
    if not target_type:
        raise ActionError("invalid_tool", f"不是动作工具：{tool_name}")

    action = str(args.get("action") or "").strip().lower()
    if action not in ACTION_WHITELIST[target_type]:
        raise ActionError(
            "invalid_action",
            f"{target_type} 不支持动作 {action or '(空)'}；允许：{', '.join(sorted(ACTION_WHITELIST[target_type]))}",
        )

    if target_type == "service":
        raw_id = args.get("service_id")
        try:
            target_id = str(int(raw_id))
        except Exception:
            raise ActionError("invalid_target", "service_id 必须是整数")
    elif target_type == "docker_container":
        target_id = str(args.get("container_id") or "").strip()
        if not target_id:
            raise ActionError("invalid_target", "container_id 不能为空")
    elif target_type == "docker_compose":
        target_id = str(args.get("project_path") or "").strip()
        if not target_id:
            raise ActionError("invalid_target", "project_path 不能为空")
    else:
        try:
            target_id = str(int(args.get("favorite_id")))
        except Exception:
            raise ActionError("invalid_target", "favorite_id 必须是整数")

    if await store.count_pending_actions(conversation_id) > 0:
        raise ActionError("pending_action_exists", "当前会话已有一个待确认动作，请先确认或拒绝")

    target = await _resolve_target(target_type, target_id)
    row = await store.create_action(
        conversation_id=conversation_id,
        message_id=message_id,
        target_type=target_type,
        target_id=target_id,
        target_name=target["name"],
        action=action,
        before_status=target["before_status"],
    )
    return {
        "action_id": row["id"],
        "target_type": target_type,
        "target_id": target_id,
        "target_name": target["name"],
        "action": action,
        "before_status": target["before_status"],
        "configured": True,
    }


async def _execute_service(target_id: str, action: str, before: str,
                           process_alive: bool | None = None) -> dict:
    from routers.terminal import start_service, stop_service

    sid = int(target_id)

    def _detail(e: Exception) -> str:
        return str(getattr(e, "detail", None) or e)

    if action == "start":
        if before == "running":
            return {"ok": True, "already": "running", "message": "服务已经在运行"}
        try:
            await start_service(sid)
        except Exception as e:
            raise ActionError("action_failed", _detail(e))
        return {"ok": True, "message": "服务已启动"}
    if action == "stop":
        if before == "stopped":
            return {"ok": True, "already": "stopped", "message": "服务已经停止"}
        if before == "running" and process_alive is False:
            raise ActionError(
                "external_process",
                "该服务的端口在监听，但不是由面板启动的进程；AI 无法安全停止它，请到端口监控或终端处理",
            )
        try:
            await stop_service(sid)
        except Exception as e:
            raise ActionError("action_failed", _detail(e))
        return {"ok": True, "message": "服务已停止"}
    if action == "restart":
        if before != "running":
            raise ActionError("not_running", "服务当前未运行，无法重启；可以改为启动")
        if process_alive is False:
            raise ActionError(
                "external_process",
                "该服务由外部进程运行，AI 无法安全重启；请到端口监控或终端处理",
            )
        try:
            await stop_service(sid)
            await start_service(sid)
        except Exception as e:
            raise ActionError("action_failed", _detail(e))
        return {"ok": True, "message": "服务已重启"}
    raise ActionError("invalid_action", f"不支持的服务动作：{action}")


async def _execute_container(target_id: str, action: str, before: str) -> dict:
    c = await _find_container(target_id)
    cid = str(c.get("id") or "")
    if not cid:
        raise ActionError("invalid_target", "容器 ID 为空")
    if action == "start" and before == "running":
        return {"ok": True, "already": "running", "message": "容器已经在运行"}
    if action == "stop" and before == "stopped":
        return {"ok": True, "already": "stopped", "message": "容器已经停止"}
    res = await asyncio.to_thread(container_action, cid, action)
    if not res.get("ok"):
        raise ActionError("action_failed", res.get("output") or "容器操作失败")
    return {"ok": True, "message": f"容器已执行 {action}", "output": res.get("output", "")}


async def _execute_compose(project_path: str, action: str, before: str) -> dict:
    if action == "stop" and before == "stopped":
        return {"ok": True, "already": "stopped", "message": "Compose 项目已经停止"}
    res = await asyncio.to_thread(compose_action, project_path, action)
    if not res.get("ok"):
        raise ActionError("action_failed", res.get("output") or "Compose 操作失败")
    return {"ok": True, "message": f"Compose 已执行 {action}", "output": res.get("output", "")}


async def _execute_favorite(target_id: str, action: str) -> dict:
    for t in await catalog.favorite_terminals():
        if str(t.get("id")) == str(target_id):
            path = t.get("path") or ""
            name = await asyncio.to_thread(open_terminal_at, path)
            if not name:
                raise ActionError("action_failed", f"无法打开终端：{path}")
            return {"ok": True, "message": f"已打开终端：{name}", "terminal": name}
    raise ActionError("target_not_found", f"常用终端不存在：{target_id}")


async def _after_status(target_type: str, target_id: str) -> str:
    try:
        if target_type == "service":
            catalog.invalidate_service_cache()
            svc = await catalog.service_detail(int(target_id))
            return svc.get("live_status") or "unknown"
        if target_type == "docker_container":
            catalog.invalidate_docker_cache()
            c = await _find_container(target_id)
            return _status_from_container(c)
        if target_type == "docker_compose":
            info = await catalog.docker_info(force=True)
            for p in info.get("compose") or []:
                if p.get("path") == target_id or p.get("name") == target_id:
                    return await _compose_status(p.get("path") or target_id)
            return "unknown"
        if target_type == "favorite_terminal":
            return "opened"
    except Exception:
        return "unknown"
    return "unknown"


async def confirm(action_id: int, confirmed_by: str = "local") -> dict:
    row = await store.get_action(action_id)
    if not row:
        raise ActionError("not_found", "动作不存在", 404)
    if row.get("status") != "pending":
        raise ActionError("already_handled", f"动作已处理（当前状态：{row.get('status')}）", 409)

    created = _parse_created_at(row.get("created_at") or "")
    if created and (datetime.now().timestamp() - created) > 600:
        await store.finish_action(action_id, "expired", error="动作已过期，请重新发起")
        raise ActionError("expired", "动作已过期，请重新发起", 410)

    if not await store.claim_action(action_id, confirmed_by):
        raise ActionError("already_handled", "动作已被处理，请勿重复确认", 409)

    target_type = row.get("target_type") or ""
    target_id = str(row.get("target_id") or "")
    action_name = row.get("action") or ""
    before = row.get("before_status") or ""

    try:
        # 重新校验目标仍存在，并以“确认时”的状态为准
        target = await _resolve_target(target_type, target_id)
        fresh_before = target.get("before_status") or before
        fresh_process_alive = (target.get("data") or {}).get("process_alive")

        async def run() -> dict:
            if target_type == "service":
                return await _execute_service(target_id, action_name, fresh_before,
                                              fresh_process_alive)
            if target_type == "docker_container":
                return await _execute_container(target_id, action_name, fresh_before)
            if target_type == "docker_compose":
                return await _execute_compose(target_id, action_name, fresh_before)
            if target_type == "favorite_terminal":
                return await _execute_favorite(target_id, action_name)
            raise ActionError("invalid_target", f"不支持的目标类型：{target_type}")

        result = await asyncio.wait_for(run(), timeout=config.AI_ACTION_TIMEOUT)
        after = await _after_status(target_type, target_id)
        await store.finish_action(action_id, "done", after_status=after, result=result)
        updated = await store.get_action(action_id) or row
        return {**updated, "result": result}
    except asyncio.TimeoutError:
        msg = f"动作执行超时（>{config.AI_ACTION_TIMEOUT:.0f}s）"
        await store.finish_action(action_id, "failed", error=msg)
        raise ActionError("timeout", msg, 504)
    except ActionError as e:
        await store.finish_action(action_id, "failed", error=e.message)
        raise
    except Exception as e:
        msg = str(e)
        await store.finish_action(action_id, "failed", error=msg)
        raise ActionError("action_failed", msg, 400)


async def reject(action_id: int, confirmed_by: str = "local") -> dict:
    row = await store.get_action(action_id)
    if not row:
        raise ActionError("not_found", "动作不存在", 404)
    if not await store.reject_action(action_id, confirmed_by):
        raise ActionError("already_handled", "动作已处理，无法拒绝", 409)
    updated = await store.get_action(action_id) or row
    return {**updated, "status": "rejected"}


async def list_actions(conversation_id: int | None = None, limit: int = 100) -> list[dict]:
    return await store.list_actions(conversation_id, limit)


def action_to_text(action: dict) -> str:
    return json.dumps({
        "action_id": action.get("id") or action.get("action_id"),
        "target_type": action.get("target_type"),
        "target_name": action.get("target_name"),
        "action": action.get("action"),
        "before_status": action.get("before_status"),
        "after_status": action.get("after_status"),
        "status": action.get("status"),
    }, ensure_ascii=False)
