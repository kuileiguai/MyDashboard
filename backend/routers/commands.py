"""M1 命令手册 路由"""

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from database import get_db

router = APIRouter()


class CommandCreate(BaseModel):
    category: str = ""
    command: str
    description: str = ""
    params_json: str = "[]"
    examples_json: str = "[]"


class CommandUpdate(BaseModel):
    category: str = None
    command: str = None
    description: str = None
    params_json: str = None
    examples_json: str = None
    is_favorite: bool = None


@router.get("")
async def list_commands(keyword: str = "", category: str = ""):
    query = "SELECT * FROM commands WHERE 1=1"
    params = []
    if keyword:
        query += " AND (command LIKE ? OR description LIKE ? OR category LIKE ?)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY is_favorite DESC, use_count DESC, id ASC"
    async with get_db() as db:
        rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


@router.post("")
async def create_command(body: CommandCreate):
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO commands (category, command, description, params_json, examples_json) VALUES (?,?,?,?,?)",
            (body.category, body.command, body.description, body.params_json, body.examples_json),
        )
        await db.commit()
        return {"id": cur.lastrowid}


@router.put("/{cmd_id}")
async def update_command(cmd_id: int, body: CommandUpdate):
    fields = {}
    if body.category is not None: fields["category"] = body.category
    if body.command is not None: fields["command"] = body.command
    if body.description is not None: fields["description"] = body.description
    if body.params_json is not None: fields["params_json"] = body.params_json
    if body.examples_json is not None: fields["examples_json"] = body.examples_json
    if body.is_favorite is not None: fields["is_favorite"] = 1 if body.is_favorite else 0
    if not fields:
        raise HTTPException(400, "No fields to update")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    set_clause += ", updated_at = CURRENT_TIMESTAMP"
    values = list(fields.values()) + [cmd_id]
    async with get_db() as db:
        await db.execute(f"UPDATE commands SET {set_clause} WHERE id = ?", values)
        await db.commit()
    return {"ok": True}


@router.delete("/{cmd_id}")
async def delete_command(cmd_id: int):
    async with get_db() as db:
        await db.execute("DELETE FROM commands WHERE id = ?", (cmd_id,))
        await db.commit()
    return {"ok": True}


@router.post("/{cmd_id}/favorite")
async def toggle_favorite(cmd_id: int):
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT is_favorite FROM commands WHERE id = ?", (cmd_id,))
        if not row:
            raise HTTPException(404, "Not found")
        new_val = 0 if row[0]["is_favorite"] else 1
        await db.execute("UPDATE commands SET is_favorite = ? WHERE id = ?", (new_val, cmd_id))
        await db.commit()
    return {"is_favorite": bool(new_val)}


# ── M1-F11: 使用频次统计 ──

@router.post("/{cmd_id}/use")
async def record_use(cmd_id: int):
    """记录命令使用（复制/执行），递增 use_count"""
    async with get_db() as db:
        await db.execute("UPDATE commands SET use_count = use_count + 1 WHERE id = ?", (cmd_id,))
        await db.execute("INSERT INTO usage_stats (action, ref_id) VALUES ('use', ?)", (cmd_id,))
        await db.commit()
    return {"ok": True}


@router.get("/top")
async def top_commands(limit: int = 10):
    """M1-F11: 使用频次 Top 榜"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM commands WHERE use_count > 0 ORDER BY use_count DESC LIMIT ?", (limit,)
        )
    return [dict(r) for r in rows]


# ── M1-F10: 导入/导出 ──

@router.get("/export")
async def export_commands():
    """M1-F10: 导出全部命令为 JSON 下载"""
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM commands ORDER BY id")
    return [dict(r) for r in rows]


class ImportPayload(BaseModel):
    commands: list[dict]


@router.post("/import")
async def import_commands(body: ImportPayload):
    """M1-F10: 从 JSON 导入命令，返回新增数量"""
    count = 0
    async with get_db() as db:
        for cmd in body.commands:
            if not cmd.get("command"):
                continue
            params = cmd.get("params")
            examples = cmd.get("examples")
            await db.execute(
                "INSERT INTO commands (category, command, description, params_json, examples_json, is_favorite) VALUES (?,?,?,?,?,?)",
                (
                    cmd.get("category", ""), cmd["command"], cmd.get("description", ""),
                    json.dumps(params) if isinstance(params, list) else cmd.get("params_json", "[]"),
                    json.dumps(examples) if isinstance(examples, list) else cmd.get("examples_json", "[]"),
                    cmd.get("is_favorite", 0),
                ),
            )
            count += 1
        await db.commit()
    return {"ok": True, "imported": count}


# ── M1-F9: 终端历史自动收录 ──

class HistoryRecord(BaseModel):
    session_id: str = ""
    command: str
    cwd: str = ""
    source: str = "terminal"  # terminal=面板内PTY, external=外部终端, shell=shell历史导入, command=命令手册发送


@router.get("/history")
async def list_history(limit: int = 100, session_id: str = "", favorite: bool = None, q: str = ""):
    query = "SELECT * FROM terminal_history WHERE 1=1"
    params = []
    if session_id:
        query += " AND session_id = ?"
        params.append(session_id)
    if favorite is not None:
        query += " AND is_favorite = ?"
        params.append(1 if favorite else 0)
    if q:
        query += " AND command LIKE ?"
        params.append(f"%{q}%")
    query += " ORDER BY is_favorite DESC, id DESC LIMIT ?"
    params.append(limit)
    async with get_db() as db:
        rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


@router.post("/history")
async def record_history(body: HistoryRecord):
    """前端在发送命令到终端时调用此接口记录"""
    cmd = body.command.strip()
    if not cmd or len(cmd) > 500:
        return {"ok": True}
    async with get_db() as db:
        await db.execute(
            "INSERT INTO terminal_history (session_id, command, cwd, source) VALUES (?,?,?,?)",
            (body.session_id, cmd, body.cwd, body.source),
        )
        await db.commit()
    return {"ok": True}


@router.get("/history/from-shell")
async def history_from_shell(limit: int = 80):
    """解析 ~/.bash_history / ~/.zsh_history，去重后返回最近命令"""
    import os
    history_paths = []
    home = os.path.expanduser("~")
    for f in (os.path.join(home, ".bash_history"), os.path.join(home, ".zsh_history")):
        if os.path.exists(f):
            history_paths.append(f)
    if not history_paths:
        return {"commands": [], "message": "未找到 shell 历史文件"}

    commands = []
    seen = set()
    for hp in history_paths:
        try:
            with open(hp, "r", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            continue
        for raw in reversed(lines):
            cmd = raw.rstrip("\n\r")
            # zsh 历史格式: ": 1234567890:0;command"
            if ";" in cmd and cmd.startswith(": "):
                cmd = cmd.split(";", 1)[1]
            cmd = cmd.strip()
            if not cmd or len(cmd) > 200:
                continue
            if cmd in seen:
                continue
            seen.add(cmd)
            commands.append(cmd)
            if len(commands) >= limit:
                break
        if len(commands) >= limit:
            break
    return {"commands": commands}


@router.post("/history/{hist_id}/favorite")
async def toggle_history_favorite(hist_id: int):
    """切换某条收录指令的常用标记"""
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT is_favorite FROM terminal_history WHERE id = ?", (hist_id,))
        if not row:
            raise HTTPException(404, "History not found")
        new_val = 0 if row[0]["is_favorite"] else 1
        await db.execute("UPDATE terminal_history SET is_favorite = ? WHERE id = ?", (new_val, hist_id))
        await db.commit()
    return {"is_favorite": bool(new_val)}


@router.post("/history/{hist_id}/convert")
async def convert_history(hist_id: int):
    """M1-F9: 历史命令一键转存为命令条目（若已存在则跳过）"""
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT * FROM terminal_history WHERE id = ?", (hist_id,))
        if not row:
            raise HTTPException(404, "History not found")
        h = row[0]
        # 查重：命令已存在则不再重复创建
        dup = await db.execute_fetchall(
            "SELECT id FROM commands WHERE command = ?", (h["command"],)
        )
        if dup:
            return {"id": dup[0]["id"], "duplicate": True}
        cur = await db.execute(
            "INSERT INTO commands (category, command, description, params_json, examples_json) VALUES (?,?,?,?,?)",
            ("历史转存", h["command"], "从终端历史自动收录", "[]", "[]"),
        )
        await db.commit()
        return {"id": cur.lastrowid, "duplicate": False}


@router.delete("/history/{hist_id}")
async def delete_history(hist_id: int):
    async with get_db() as db:
        await db.execute("DELETE FROM terminal_history WHERE id = ?", (hist_id,))
        await db.commit()
    return {"ok": True}


# ── 小屏聚合模糊查找 ──

@router.get("/lookup")
async def lookup(q: str = "", limit: int = 30):
    """聚合命令手册 + 终端历史，供悬浮小屏模糊查找"""
    results = []
    like = f"%{q}%" if q else None

    async with get_db() as db:
        # 命令手册
        if like:
            rows = await db.execute_fetchall(
                "SELECT id, command, description, category, is_favorite, use_count FROM commands "
                "WHERE command LIKE ? OR description LIKE ? OR category LIKE ? "
                "ORDER BY is_favorite DESC, use_count DESC LIMIT ?",
                (like, like, like, limit),
            )
        else:
            rows = await db.execute_fetchall(
                "SELECT id, command, description, category, is_favorite, use_count FROM commands "
                "ORDER BY is_favorite DESC, use_count DESC LIMIT ?",
                (limit,),
            )
        for r in rows:
            results.append({
                "id": r["id"], "command": r["command"], "description": r["description"],
                "category": r["category"], "source": "command",
                "is_favorite": bool(r["is_favorite"]), "use_count": r["use_count"],
            })

        # 终端历史（含自动收录的 shell 历史）
        if like:
            rows2 = await db.execute_fetchall(
                "SELECT id, command, source, is_favorite FROM terminal_history "
                "WHERE command LIKE ? ORDER BY is_favorite DESC, id DESC LIMIT ?",
                (like, limit),
            )
        else:
            rows2 = await db.execute_fetchall(
                "SELECT id, command, source, is_favorite FROM terminal_history "
                "ORDER BY is_favorite DESC, id DESC LIMIT ?",
                (limit,),
            )
        for r in rows2:
            results.append({
                "id": r["id"], "command": r["command"], "description": "",
                "category": "", "source": r["source"],
                "is_favorite": bool(r["is_favorite"]), "use_count": 0,
            })

    return results
