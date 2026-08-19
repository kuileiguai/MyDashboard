"""M4 终端中心 REST 路由"""

import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_db
from services.pty_manager import pty_manager
from services.tmux_service import list_tmux_sessions, tmux_info, attach_tmux_session
from services.external_terminal import (
    list_terminal_windows, focus_window, close_window,
    send_command_to_window, send_keys_to_window, send_command_to_active_window,
)

router = APIRouter()


class TerminalCreate(BaseModel):
    name: str = "terminal"
    cwd: str = "~"
    shell: str = "/bin/bash"
    command: str = ""


class TerminalRename(BaseModel):
    name: str


class TerminalResize(BaseModel):
    rows: int = 24
    cols: int = 80


@router.post("/create")
async def create_terminal(body: TerminalCreate):
    sid = pty_manager.create(body.name, body.cwd, body.shell, body.command)
    return {"session_id": sid}


@router.get("/list")
async def list_terminals():
    return pty_manager.list_sessions()


@router.put("/{sid}/rename")
async def rename_terminal(sid: str, body: TerminalRename):
    pty_manager.rename(sid, body.name)
    return {"ok": True}


@router.post("/{sid}/resize")
async def resize_terminal(sid: str, body: TerminalResize):
    pty_manager.resize(sid, body.rows, body.cols)
    return {"ok": True}


@router.delete("/{sid}")
async def close_terminal(sid: str):
    pty_manager.kill(sid)
    return {"ok": True}


# ── M4-F11: tmux 集成 ──

@router.get("/tmux/list")
async def tmux_list():
    return {"sessions": list_tmux_sessions(), "info": tmux_info()}


@router.post("/tmux/attach")
async def tmux_attach(name: str, read_only: bool = False):
    cmd = attach_tmux_session(name, read_only)
    sid = pty_manager.create(f"tmux:{name}", "~", "/bin/bash", cmd)
    return {"session_id": sid, "command": cmd}


# ── 外部终端窗口检测与控制 ──

@router.get("/external/list")
async def external_list():
    """列出本机已打开的外部终端窗口（GNOME Terminal、xterm 等）"""
    return {"terminals": list_terminal_windows()}


@router.post("/external/{win_id}/focus")
async def external_focus(win_id: str):
    ok = focus_window(win_id)
    return {"ok": ok}


@router.post("/external/{win_id}/close")
async def external_close(win_id: str):
    ok = close_window(win_id)
    return {"ok": ok}


class SendCommand(BaseModel):
    command: str


@router.post("/external/{win_id}/send")
async def external_send(win_id: str, body: SendCommand):
    """向外部终端窗口发送命令并回车执行"""
    ok = send_command_to_window(win_id, body.command)
    return {"ok": ok}


@router.post("/active/send")
async def active_send(body: SendCommand):
    """向最近活动的终端窗口发送命令（不自动回车，由用户自行确认执行；悬浮小屏"点即输入"）"""
    ok = send_command_to_active_window(body.command, press_enter=False)
    return {"ok": ok}


@router.post("/external/{win_id}/type")
async def external_type(win_id: str, text: str = ""):
    """向外部终端窗口发送文本（不回车）"""
    ok = send_keys_to_window(win_id, text)
    return {"ok": ok}


# ── 外部终端别名管理 ──

@router.get("/external/aliases")
async def get_aliases():
    """获取终端窗口别名映射 {win_id: alias_name}"""
    import json
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'terminal_aliases'")
    if row:
        try: return json.loads(row[0]["value"])
        except Exception: pass
    return {}


class AliasSave(BaseModel):
    win_id: str
    alias: str


@router.post("/external/aliases")
async def save_alias(body: AliasSave):
    """保存单个终端窗口别名"""
    import json
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'terminal_aliases'")
        aliases = {}
        if row:
            try: aliases = json.loads(row[0]["value"])
            except Exception: pass
        if body.alias.strip():
            aliases[body.win_id] = body.alias.strip()
        else:
            aliases.pop(body.win_id, None)
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('terminal_aliases', ?)",
            (json.dumps(aliases),),
        )
        await db.commit()
    return {"ok": True, "aliases": aliases}


@router.delete("/external/aliases/{win_id}")
async def delete_alias(win_id: str):
    """删除终端别名"""
    import json
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'terminal_aliases'")
        aliases = json.loads(row[0]["value"]) if row else {}
        aliases.pop(win_id, None)
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('terminal_aliases', ?)",
            (json.dumps(aliases),),
        )
        await db.commit()
    return {"ok": True}
