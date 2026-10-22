"""AI 会话/消息/动作的持久化。

所有 SQL 集中在这里，路由和业务逻辑不直接拼 SQL。
"""

from __future__ import annotations

import json
from typing import Any

from database import get_db

JSON_FIELDS = {
    "context_json", "tool_calls_json", "args_json", "result_json", "extra_json",
}


def _loads(raw: str | None, default: Any):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _rowdict(row) -> dict:
    d = dict(row)
    for key in list(d.keys()):
        if key in JSON_FIELDS:
            target = key[:-5] if key.endswith("_json") else key
            if key == "context_json":
                target = "context"
            elif key == "tool_calls_json":
                target = "tool_calls"
            elif key == "args_json":
                target = "args"
            elif key == "result_json":
                target = "result"
            elif key == "extra_json":
                target = "extra"
            d[target] = _loads(d.get(key), {} if target in ("context", "args", "result", "extra") else [])
    return d


# ── 会话 ──────────────────────────────────────────────────────────

async def create_conversation(title: str = "", project_id: int | None = None,
                              model: str = "", context: dict | None = None) -> dict:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO ai_conversations (title, project_id, model, context_json) VALUES (?,?,?,?)",
            (title or "", project_id, model or "", json.dumps(context or {}, ensure_ascii=False)),
        )
        await db.commit()
        cid = cur.lastrowid
        rows = await db.execute_fetchall("SELECT * FROM ai_conversations WHERE id = ?", (cid,))
    return _rowdict(rows[0])


async def list_conversations(limit: int = 50) -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM ai_conversations WHERE archived = 0 "
            "ORDER BY updated_at DESC, id DESC LIMIT ?", (max(1, min(200, limit)),))
    return [_rowdict(r) for r in rows]


async def get_conversation(cid: int) -> dict | None:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM ai_conversations WHERE id = ?", (cid,))
    return _rowdict(rows[0]) if rows else None


async def update_conversation(cid: int, title: str | None = None,
                              archived: bool | None = None) -> bool:
    fields, params = [], []
    if title is not None:
        fields.append("title = ?")
        params.append(title.strip()[:120])
    if archived is not None:
        fields.append("archived = ?")
        params.append(1 if archived else 0)
    if not fields:
        return False
    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(cid)
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_conversations SET {', '.join(fields)} WHERE id = ?", params)
        await db.commit()
        return cur.rowcount > 0


async def delete_conversation(cid: int) -> bool:
    async with get_db() as db:
        await db.execute("DELETE FROM ai_messages WHERE conversation_id = ?", (cid,))
        await db.execute("DELETE FROM ai_tool_calls WHERE conversation_id = ?", (cid,))
        await db.execute("DELETE FROM ai_actions WHERE conversation_id = ?", (cid,))
        cur = await db.execute("DELETE FROM ai_conversations WHERE id = ?", (cid,))
        await db.commit()
    return cur.rowcount > 0


async def touch_conversation(cid: int, title: str | None = None) -> None:
    async with get_db() as db:
        if title:
            await db.execute(
                "UPDATE ai_conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title.strip()[:120], cid))
        else:
            await db.execute(
                "UPDATE ai_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (cid,))
        await db.commit()


# ── 消息 ──────────────────────────────────────────────────────────

async def add_message(cid: int, role: str, content: str = "",
                      tool_calls: list | None = None, tool_call_id: str = "",
                      tokens_in: int = 0, tokens_out: int = 0,
                      tokens_estimated: bool = False) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO ai_messages "
            "(conversation_id, role, content, tool_calls_json, tool_call_id, "
            "tokens_in, tokens_out, tokens_estimated) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, role, content or "", json.dumps(tool_calls or [], ensure_ascii=False),
             tool_call_id or "", tokens_in, tokens_out, 1 if tokens_estimated else 0),
        )
        await db.execute(
            "UPDATE ai_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (cid,))
        await db.commit()
        return cur.lastrowid


async def list_messages(cid: int, limit: int = 200) -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM ai_messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?", (cid, max(1, min(1000, limit))))
    items = [_rowdict(r) for r in rows]
    items.reverse()
    return items


async def conversation_usage(cid: int) -> dict:
    """本会话累计 token。模型未返回 usage 时，tokens_estimated=1。"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT COALESCE(SUM(tokens_in), 0) AS tin, "
            "COALESCE(SUM(tokens_out), 0) AS tout, "
            "COALESCE(SUM(tokens_estimated), 0) AS estimated "
            "FROM ai_messages WHERE conversation_id = ?", (cid,))
    row = rows[0] if rows else None
    tin = int(row["tin"] or 0) if row else 0
    tout = int(row["tout"] or 0) if row else 0
    return {
        "input": tin,
        "output": tout,
        "total": tin + tout,
        "estimated": bool(row["estimated"]) if row else False,
    }


# ── 工具调用记录 ──────────────────────────────────────────────────

async def record_tool_call(cid: int, message_id: int | None, name: str,
                           args: dict, result: dict, status: str = "ok",
                           duration_ms: int = 0) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO ai_tool_calls "
            "(conversation_id, message_id, name, args_json, result_json, status, duration_ms) "
            "VALUES (?,?,?,?,?,?,?)",
            (cid, message_id, name, json.dumps(args or {}, ensure_ascii=False),
             json.dumps(result or {}, ensure_ascii=False), status, duration_ms),
        )
        await db.commit()


# ── 动作 ──────────────────────────────────────────────────────────

async def create_action(conversation_id: int, message_id: int | None, target_type: str,
                        target_id: str, target_name: str, action: str,
                        before_status: str = "") -> dict:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO ai_actions "
            "(conversation_id, message_id, target_type, target_id, target_name, action, before_status) "
            "VALUES (?,?,?,?,?,?,?)",
            (conversation_id, message_id, target_type, str(target_id), target_name,
             action, before_status or ""),
        )
        await db.commit()
        rows = await db.execute_fetchall("SELECT * FROM ai_actions WHERE id = ?", (cur.lastrowid,))
    return _rowdict(rows[0])


async def get_action(aid: int) -> dict | None:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM ai_actions WHERE id = ?", (aid,))
    return _rowdict(rows[0]) if rows else None


async def list_actions(conversation_id: int | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM ai_actions"
    params: list[Any] = []
    if conversation_id is not None:
        sql += " WHERE conversation_id = ?"
        params.append(conversation_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(500, limit)))
    async with get_db() as db:
        rows = await db.execute_fetchall(sql, params)
    return [_rowdict(r) for r in rows]


async def count_pending_actions(cid: int) -> int:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT COUNT(*) AS c FROM ai_actions WHERE conversation_id = ? AND status = 'pending'",
            (cid,))
    return rows[0]["c"] if rows else 0


async def claim_action(aid: int, confirmed_by: str = "local") -> bool:
    """原子占用 pending 动作，避免双击/并发重复执行。"""
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE ai_actions SET status = 'confirmed', confirmed_by = ?, "
            "confirmed_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'pending'",
            (confirmed_by, aid))
        await db.commit()
        return cur.rowcount == 1


async def finish_action(aid: int, status: str, after_status: str = "",
                        result: dict | None = None, error: str = "") -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE ai_actions SET status = ?, after_status = ?, result_json = ?, "
            "error = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, after_status or "", json.dumps(result or {}, ensure_ascii=False),
             error or "", aid))
        await db.commit()


async def reject_action(aid: int, confirmed_by: str = "local") -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE ai_actions SET status = 'rejected', confirmed_by = ?, "
            "finished_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'pending'",
            (confirmed_by, aid))
        await db.commit()
        return cur.rowcount == 1


async def set_action_message_id(aid: int, message_id: int) -> None:
    async with get_db() as db:
        await db.execute("UPDATE ai_actions SET message_id = ? WHERE id = ?",
                         (message_id, aid))
        await db.commit()
