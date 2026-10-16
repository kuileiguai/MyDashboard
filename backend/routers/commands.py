"""M1 命令手册 路由"""

import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from database import get_db
from services.history_time import next_ts

router = APIRouter()


class CommandCreate(BaseModel):
    category: str = ""
    service: str = ""      # 二级分类：所属服务，如 nginx / redis
    scenario: str = ""     # 二级分类：所属场景，如 排障 / 部署
    command: str
    description: str = ""
    params_json: str = "[]"
    examples_json: str = "[]"


class CommandUpdate(BaseModel):
    category: str = None
    service: str = None
    scenario: str = None
    command: str = None
    description: str = None
    params_json: str = None
    examples_json: str = None
    is_favorite: bool = None


@router.get("")
async def list_commands(keyword: str = "", category: str = "",
                        service: str = "", scenario: str = ""):
    query = "SELECT * FROM commands WHERE 1=1"
    params = []
    if keyword:
        query += (" AND (command LIKE ? OR description LIKE ? OR category LIKE ? "
                  "OR service LIKE ? OR scenario LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw, kw])
    if category:
        query += " AND category = ?"
        params.append(category)
    if service:
        query += " AND service = ?"
        params.append(service)
    if scenario:
        query += " AND scenario = ?"
        params.append(scenario)
    query += " ORDER BY is_favorite DESC, use_count DESC, id ASC"
    async with get_db() as db:
        rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


@router.get("/facets")
async def command_facets():
    """分类 / 服务 / 场景 选项。优先取自 taxonomy 字典表（按 sort 排序），
    commands 表里已用但字典里没有的"孤儿"值会补在后面，方便逐步收编。"""
    type_map = {"category": "categories", "service": "services", "scenario": "scenarios"}
    result = {v: [] for v in type_map.values()}
    seen = {k: set() for k in type_map}
    async with get_db() as db:
        dict_rows = await db.execute_fetchall(
            "SELECT type, value FROM taxonomy ORDER BY type, sort ASC, value ASC")
        for r in dict_rows:
            t, v = r["type"], r["value"]
            if t in type_map:
                result[type_map[t]].append(v)
                seen[t].add(v)
        used_rows = await db.execute_fetchall(
            "SELECT 'category' AS t, category AS v FROM commands WHERE category != '' "
            "UNION ALL SELECT 'service', service FROM commands WHERE service != '' "
            "UNION ALL SELECT 'scenario', scenario FROM commands WHERE scenario != ''")
        for r in used_rows:
            t, v = r["t"], r["v"]
            if t in type_map and v not in seen[t]:
                result[type_map[t]].append(v)
                seen[t].add(v)
    return result


@router.post("")
async def create_command(body: CommandCreate):
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO commands (category, service, scenario, command, description, params_json, examples_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (body.category, body.service, body.scenario, body.command,
             body.description, body.params_json, body.examples_json),
        )
        for t in ("category", "service", "scenario"):
            await _ensure_taxonomy(db, t, getattr(body, t))
        await db.commit()
        return {"id": cur.lastrowid}


# ── 分类字典管理（一级分类 / 所属服务 / 所属场景）──
# 必须在 /{cmd_id} 之前注册，否则 PUT/DELETE 会被 cmd_id(int) 抢先匹配。

TAXONOMY_TYPES = ("category", "service", "scenario")


def _validate_type(t: str):
    if t not in TAXONOMY_TYPES:
        raise HTTPException(400, f"type 必须是 {TAXONOMY_TYPES} 之一")


async def _ensure_taxonomy(db, type_: str, value: str):
    """把某个值收录进字典（幂等）。被 create/update/import/convert 共用。"""
    v = (value or "").strip()
    if not v or type_ not in TAXONOMY_TYPES:
        return
    if len(v) > 64:
        return
    await db.execute(
        "INSERT OR IGNORE INTO taxonomy (type, value) VALUES (?, ?)",
        (type_, v))


@router.get("/taxonomy")
async def list_taxonomy(type: str = ""):
    """type 为空返回全部；否则只返回指定类型。带 commands 表里的引用计数。"""
    query = """
        SELECT t.type, t.value, t.sort, t.created_at,
               CASE t.type
                 WHEN 'category' THEN (SELECT COUNT(*) FROM commands c WHERE c.category = t.value)
                 WHEN 'service'  THEN (SELECT COUNT(*) FROM commands c WHERE c.service  = t.value)
                 WHEN 'scenario' THEN (SELECT COUNT(*) FROM commands c WHERE c.scenario = t.value)
               END AS ref_count
        FROM taxonomy t
    """
    params = []
    if type:
        _validate_type(type)
        query += " WHERE t.type = ?"
        params.append(type)
    query += " ORDER BY t.type, t.sort ASC, t.value ASC"
    async with get_db() as db:
        rows = await db.execute_fetchall(query, params)
    return [dict(r) for r in rows]


class TaxonomyCreate(BaseModel):
    type: str
    value: str
    sort: int = 0


@router.post("/taxonomy")
async def create_taxonomy(body: TaxonomyCreate):
    _validate_type(body.type)
    v = body.value.strip()
    if not v:
        raise HTTPException(400, "value 不能为空")
    if len(v) > 64:
        raise HTTPException(400, "value 长度不能超过 64")
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO taxonomy (type, value, sort) VALUES (?, ?, ?)",
            (body.type, v, body.sort))
        await db.commit()
    return {"ok": True}


class TaxonomyUpdate(BaseModel):
    type: str           # 当前 type
    value: str          # 当前 value
    new_value: str | None = None
    new_type: str | None = None
    sort: int | None = None


@router.put("/taxonomy")
async def update_taxonomy(body: TaxonomyUpdate):
    _validate_type(body.type)
    new_v = (body.new_value or body.value).strip()
    new_t = body.new_type or body.type
    if not new_v:
        raise HTTPException(400, "new_value 不能为空")
    _validate_type(new_t)
    async with get_db() as db:
        # 值或类型变了：把 commands 表里引用此值的字段一起改掉，保持一致
        if new_v != body.value or new_t != body.type:
            await db.execute(
                f"UPDATE commands SET {body.type} = ? WHERE {body.type} = ?",
                (new_v, body.value))
        sort_val = body.sort if body.sort is not None else 0
        await db.execute(
            "UPDATE taxonomy SET value = ?, type = ?, sort = ? "
            "WHERE type = ? AND value = ?",
            (new_v, new_t, sort_val, body.type, body.value))
        await db.commit()
    return {"ok": True}


@router.delete("/taxonomy")
async def delete_taxonomy(type: str, value: str, cascade: str = "clear"):
    """cascade: clear=把 commands 表里引用此值的字段清空（当前只支持 clear）"""
    _validate_type(type)
    if cascade not in ("clear",):
        raise HTTPException(400, "cascade 仅支持 clear")
    async with get_db() as db:
        await db.execute(
            f"UPDATE commands SET {type} = '' WHERE {type} = ?", (value,))
        await db.execute(
            "DELETE FROM taxonomy WHERE type = ? AND value = ?", (type, value))
        await db.commit()
    return {"ok": True}


@router.put("/{cmd_id}")
async def update_command(cmd_id: int, body: CommandUpdate):
    fields = {}
    if body.category is not None: fields["category"] = body.category
    if body.service is not None: fields["service"] = body.service
    if body.scenario is not None: fields["scenario"] = body.scenario
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
        for t in ("category", "service", "scenario"):
            if t in fields:
                await _ensure_taxonomy(db, t, fields[t])
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
    """M1-F11: 使用频次 Top 榜。

    基于 terminal_history 的真实执行次数（SUM(run_count)）排榜，
    而不是手册里的 use_count（复制计数，不反映真实使用）。
    """
    async with get_db() as db:
        rows = await db.execute_fetchall(
            """
            SELECT c.*, COALESCE(h.exec_count, 0) AS exec_count
            FROM commands c
            LEFT JOIN (
                SELECT command, SUM(run_count) AS exec_count
                FROM terminal_history
                GROUP BY command
            ) h ON c.command = h.command
            WHERE COALESCE(h.exec_count, 0) > 0
            ORDER BY exec_count DESC, c.id ASC
            LIMIT ?
            """,
            (limit,),
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
            cat, svc, scn = cmd.get("category", ""), cmd.get("service", ""), cmd.get("scenario", "")
            await db.execute(
                "INSERT INTO commands (category, service, scenario, command, description, params_json, examples_json, is_favorite) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    cat, svc, scn,
                    cmd["command"], cmd.get("description", ""),
                    json.dumps(params) if isinstance(params, list) else cmd.get("params_json", "[]"),
                    json.dumps(examples) if isinstance(examples, list) else cmd.get("examples_json", "[]"),
                    cmd.get("is_favorite", 0),
                ),
            )
            for t, v in (("category", cat), ("service", svc), ("scenario", scn)):
                await _ensure_taxonomy(db, t, v)
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
async def list_history(limit: int = 100, offset: int = 0, session_id: str = "",
                       favorite: bool = None, q: str = ""):
    """分页返回终端历史。

    total 为「按当前筛选条件匹配到的总条数」（不带分页），供前端翻页使用；
    q 为空时 total 就是库内总数。
    """
    where = " WHERE 1=1"
    params = []
    if session_id:
        where += " AND session_id = ?"
        params.append(session_id)
    if favorite is not None:
        where += " AND is_favorite = ?"
        params.append(1 if favorite else 0)
    if q:
        where += " AND command LIKE ?"
        params.append(f"%{q}%")
    async with get_db() as db:
        cnt = await db.execute_fetchall(
            "SELECT COUNT(*) AS c FROM terminal_history" + where, params)
        total = cnt[0]["c"] if cnt else 0
        rows = await db.execute_fetchall(
            "SELECT * FROM terminal_history" + where +
            " ORDER BY is_favorite DESC, created_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [max(0, limit), max(0, offset)])
    return {"total": total, "items": [dict(r) for r in rows]}


@router.post("/history")
async def record_history(body: HistoryRecord):
    """前端在发送命令到终端时调用此接口记录。

    同一条命令只保留一行：已存在就把时间戳刷新为当前（毫秒精度）并顺延到历史最前面，
    同时累加 run_count（真实执行次数，供 Top 榜统计），
    而不是每次执行都堆积一条重复行。排序见 list_history。
    """
    cmd = body.command.strip()
    if not cmd or len(cmd) > 500:
        return {"ok": True}
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id FROM terminal_history WHERE command = ? ORDER BY id DESC LIMIT 1", (cmd,)
        )
        if rows:
            await db.execute(
                "UPDATE terminal_history SET created_at = ?, source = ?, "
                "run_count = run_count + 1, "
                "session_id = CASE WHEN ? = '' THEN session_id ELSE ? END, "
                "cwd = CASE WHEN ? = '' THEN cwd ELSE ? END "
                "WHERE id = ?",
                (next_ts(), body.source, body.session_id, body.session_id,
                 body.cwd, body.cwd, rows[0]["id"]),
            )
        else:
            await db.execute(
                "INSERT INTO terminal_history (session_id, command, cwd, source, created_at) "
                "VALUES (?,?,?,?,?)",
                (body.session_id, cmd, body.cwd, body.source, next_ts()),
            )
        await db.commit()
    return {"ok": True}


@router.get("/history/from-shell")
async def history_from_shell(limit: int = 500):
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


class ConvertPayload(BaseModel):
    """转存时可指定一级分类与二级分类（所属服务 / 所属场景）"""
    category: str = ""
    service: str = ""
    scenario: str = ""


@router.post("/history/{hist_id}/convert")
async def convert_history(hist_id: int, body: ConvertPayload | None = None):
    """M1-F9: 历史命令转存为命令条目（若已存在则跳过）。
    body 可带 category / service / scenario，不传则沿用「历史转存」。"""
    category = (body.category.strip() if body and body.category else "") or "历史转存"
    service = body.service.strip() if body and body.service else ""
    scenario = body.scenario.strip() if body and body.scenario else ""
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT * FROM terminal_history WHERE id = ?", (hist_id,))
        if not row:
            raise HTTPException(404, "History not found")
        h = row[0]
        # 查重：命令已存在则不再重复创建，但补齐空缺的二级分类
        dup = await db.execute_fetchall(
            "SELECT id, service, scenario FROM commands WHERE command = ?", (h["command"],)
        )
        if dup:
            d = dup[0]
            patch = []
            if service and not d["service"]:
                patch.append(("service", service))
            if scenario and not d["scenario"]:
                patch.append(("scenario", scenario))
            if patch:
                set_clause = ", ".join(f"{k} = ?" for k, _ in patch)
                await db.execute(
                    f"UPDATE commands SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    [v for _, v in patch] + [d["id"]],
                )
                await db.commit()
            return {"id": d["id"], "duplicate": True, "patched": len(patch)}
        cur = await db.execute(
            "INSERT INTO commands (category, service, scenario, command, description, params_json, examples_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (category, service, scenario, h["command"], "从终端历史自动收录", "[]", "[]"),
        )
        for t, v in (("category", category), ("service", service), ("scenario", scenario)):
            await _ensure_taxonomy(db, t, v)
        await db.commit()
        return {"id": cur.lastrowid, "duplicate": False, "patched": 0}


# ── 终端历史收录设置（可在界面调整，改完即时生效）──

class HistoryConfigBody(BaseModel):
    max_entries: int | None = None        # 首次导入 / 重扫时每个文件最多收录多少条
    history_global: bool | None = None    # 是否同步 /home/* 下所有用户的历史
    interval: float | None = None         # 增量同步间隔（秒）


@router.get("/history/config")
async def get_history_config():
    from services.history_sync import load_history_config
    cfg = await load_history_config()
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT COUNT(*) AS c FROM terminal_history")
        src = await db.execute_fetchall(
            "SELECT source, COUNT(*) AS c FROM terminal_history GROUP BY source")
    cfg["total"] = row[0]["c"] if row else 0
    cfg["by_source"] = {r["source"]: r["c"] for r in src}
    return cfg


@router.post("/history/config")
async def set_history_config(body: HistoryConfigBody):
    from services.history_sync import save_history_config
    payload = {}
    if body.max_entries is not None:
        payload["history_max_entries"] = max(1, min(100000, body.max_entries))
    if body.history_global is not None:
        payload["history_global"] = body.history_global
    if body.interval is not None:
        payload["history_sync_interval"] = max(1.0, min(3600.0, body.interval))
    return await save_history_config(payload)


@router.post("/history/rescan")
async def rescan_history():
    """清空各历史文件的读取偏移，下一轮同步从文件开头重读，把之前因上限没收录的命令补进来"""
    from services.history_sync import request_rescan
    await request_rescan()
    return {"ok": True, "message": "已请求重新全量扫描，几秒后刷新即可看到新增收录"}


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
                "WHERE command LIKE ? ORDER BY is_favorite DESC, created_at DESC, id DESC LIMIT ?",
                (like, limit),
            )
        else:
            rows2 = await db.execute_fetchall(
                "SELECT id, command, source, is_favorite FROM terminal_history "
                "ORDER BY is_favorite DESC, created_at DESC, id DESC LIMIT ?",
                (limit,),
            )
        for r in rows2:
            results.append({
                "id": r["id"], "command": r["command"], "description": "",
                "category": "", "source": r["source"],
                "is_favorite": bool(r["is_favorite"]), "use_count": 0,
            })

    return results


