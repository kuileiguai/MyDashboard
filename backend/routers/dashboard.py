"""M9 首页面板 + M0-F10 项目概念 路由"""

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db
from services.monitor_service import get_snapshot, get_disk_top
from services.pty_manager import pty_manager

router = APIRouter()


@router.get("/summary")
async def summary():
    snap = get_snapshot()
    active_terminals = pty_manager.list_sessions()
    async with get_db() as db:
        recent = await db.execute_fetchall(
            "SELECT * FROM recent_files ORDER BY opened_at DESC LIMIT 10"
        )
        top_cmds = await db.execute_fetchall(
            "SELECT * FROM commands WHERE use_count > 0 ORDER BY use_count DESC LIMIT 5"
        )
        projects = await db.execute_fetchall("SELECT * FROM projects ORDER BY sort_order")
    return {
        "system": snap,
        "active_terminals": active_terminals,
        "recent_files": [dict(r) for r in recent],
        "top_commands": [dict(r) for r in top_cmds],
        "projects": [dict(r) for r in projects],
    }


# ── M9-F5: 一键操作 ──

@router.get("/quick-actions")
async def list_quick_actions():
    """可配置的一键操作列表"""
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'quick_actions'")
    if rows:
        try:
            return json.loads(rows[0]["value"])
        except Exception:
            pass
    # 默认操作
    return [
        {"name": "清理 APT 缓存", "command": "sudo apt-get clean", "icon": "Delete"},
        {"name": "磁盘占用 Top10", "command": "du -sh /* 2>/dev/null | sort -h | tail -10", "icon": "PieChart"},
        {"name": "重启 Docker", "command": "sudo systemctl restart docker", "icon": "Refresh"},
        {"name": "查看大文件", "command": "find /home -type f -size +100M 2>/dev/null | head -20", "icon": "Search"},
    ]


@router.post("/quick-actions")
async def save_quick_actions(actions: list[dict]):
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('quick_actions', ?)",
            (json.dumps(actions),),
        )
        await db.commit()
    return {"ok": True}


@router.post("/execute-action")
async def execute_action(command: str = Query(...)):
    """一键执行操作——在 M4 新开终端运行"""
    sid = pty_manager.create("一键操作", "~", "/bin/bash", command)
    return {"terminal_id": sid, "command": command}


# ── M0-F10: 项目概念 ──

class ProjectCreate(BaseModel):
    name: str
    root_path: str = ""
    terminal_group: str = ""
    env_name: str = ""
    command_group: str = ""
    log_paths: str = "[]"


@router.get("/projects")
async def list_projects():
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM projects ORDER BY sort_order")
    result = []
    for r in rows:
        d = dict(r)
        d["log_paths"] = json.loads(d.get("log_paths", "[]"))
        result.append(d)
    return result


@router.post("/projects")
async def create_project(body: ProjectCreate):
    async with get_db() as db:
        cur = await db.execute(
            """INSERT INTO projects (name, root_path, terminal_group, env_name, command_group, log_paths)
               VALUES (?,?,?,?,?,?)""",
            (body.name, body.root_path, body.terminal_group, body.env_name,
             body.command_group, body.log_paths),
        )
        await db.commit()
        return {"id": cur.lastrowid}


@router.put("/projects/{pid}")
async def update_project(pid: int, body: ProjectCreate):
    async with get_db() as db:
        await db.execute(
            """UPDATE projects SET name=?,root_path=?,terminal_group=?,env_name=?,command_group=?,log_paths=?
               WHERE id=?""",
            (body.name, body.root_path, body.terminal_group, body.env_name,
             body.command_group, body.log_paths, pid),
        )
        await db.commit()
    return {"ok": True}


@router.delete("/projects/{pid}")
async def delete_project(pid: int):
    async with get_db() as db:
        await db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        await db.commit()
    return {"ok": True}


# ── M9-F5: 磁盘大文件 Top ──

@router.get("/disk-top")
async def disk_top(path: str = "~", n: int = 10):
    return await get_disk_top(path, n)
