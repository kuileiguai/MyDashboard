"""M4 终端中心 REST 路由"""

import json
import os
import shutil
import signal
import asyncio
import subprocess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from database import get_db
from services.pty_manager import pty_manager
from services.tmux_service import (
    list_tmux_sessions, tmux_info, attach_tmux_session,
    tmux_available, session_name_for_window, wait_for_session,
    find_session_by_pane_pid, pane_pid_sessions,
)
from services.external_terminal import (
    list_terminal_windows, focus_window, close_window,
    send_command_to_window, send_keys_to_window, send_command_to_active_window,
    open_terminal_at,
    get_shell_pid, shell_is_busy, inject_tmux_session,
)
from services.port_service import get_listening_ports

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
    """列出本机已打开的外部终端窗口（GNOME Terminal、xterm 等）

    附带每个窗口的 shell PID、前台忙碌状态以及是否可被 tmux 接管。
    """
    ok_tmux = tmux_available()
    pane_map = pane_pid_sessions()
    terminals = list_terminal_windows()

    for t in terminals:
        shell_pid = get_shell_pid(t.get("pid"))
        session = pane_map.get(shell_pid)
        busy, running = shell_is_busy(shell_pid) if shell_pid else (True, "无法定位 shell")
        t["shell_pid"] = shell_pid
        t["tmux_session"] = session
        t["busy"] = busy
        t["running_command"] = running
        # 已在 tmux 内可直接 attach；否则需 shell 空闲才能注入
        t["can_takeover"] = ok_tmux and (bool(session) or not busy)

    return {"terminals": terminals, "tmux_available": ok_tmux, "capture_available": shutil.which("ffmpeg") is not None}


@router.post("/external/{win_id}/focus")
async def external_focus(win_id: str):
    ok = focus_window(win_id)
    return {"ok": ok}


@router.post("/external/{win_id}/takeover")
async def external_takeover(win_id: str):
    """把某个外部终端窗口接管到面板内终端（PTY），实现远程双向操作。

    - 该终端的 shell 已在 tmux 内 → 直接 attach 同一会话；
    - 否则向窗口注入 `exec tmux new-session -A -s deckpit-w<pid>`，
      把当前 shell 挂进 tmux，再 attach。前台有程序时无法注入，返回 409。
    """
    if not tmux_available():
        raise HTTPException(400, "未安装 tmux，无法接管。请先在服务器执行: sudo apt install tmux")

    win = next((w for w in list_terminal_windows() if w["id"] == win_id), None)
    if not win:
        raise HTTPException(404, "未找到该终端窗口，请刷新列表后重试")

    shell_pid = get_shell_pid(win.get("pid"))
    cwd = win.get("cwd") or "~"

    # 已在 tmux 内：直接接管，历史回滚也能看到
    existing = find_session_by_pane_pid(shell_pid)
    if existing:
        sid = pty_manager.create(f"tmux:{existing}", cwd, "/bin/bash", attach_tmux_session(existing))
        return {
            "session_id": sid, "session_name": existing, "mode": "attach",
            "message": f"已接管现有 tmux 会话 {existing}，与该终端完全双向同步",
        }

    busy, running = shell_is_busy(shell_pid) if shell_pid else (True, "无法定位 shell")
    if busy:
        raise HTTPException(409, f"该终端前台正在运行 {running}，无法接管。请结束该程序回到 shell 提示符后重试")

    name = session_name_for_window(win.get("pid"))
    if not inject_tmux_session(win_id, name):
        raise HTTPException(500, "注入失败：无法激活该终端窗口（服务器桌面可能已锁定或不可聚焦）")

    if not wait_for_session(name, 8.0):
        raise HTTPException(504, "等待 tmux 会话建立超时，接管失败")

    sid = pty_manager.create(f"tmux:{name}", cwd, "/bin/bash", attach_tmux_session(name))
    return {
        "session_id": sid, "session_name": name, "mode": "inject",
        "message": f"已接管：该终端已挂入 tmux 会话 {name}，从现在起双向同步（接管之前的输出无法带过来）",
    }


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


# ── 常用终端（备注 + 文件夹路径，一键打开外部终端） ──

class FavoriteTerminal(BaseModel):
    name: str
    path: str


@router.get("/favorites")
async def list_favorite_terminals():
    """常用终端列表"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM favorite_terminals ORDER BY sort_order, id"
        )
    return [dict(r) for r in rows]


@router.post("/favorites")
async def create_favorite_terminal(body: FavoriteTerminal):
    name, path = body.name.strip(), body.path.strip()
    if not name:
        raise HTTPException(400, "备注不能为空")
    if not path:
        raise HTTPException(400, "文件夹路径不能为空")
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO favorite_terminals (name, path, sort_order) VALUES (?,?,?)",
            (name, path, 0),
        )
        await db.commit()
    return {"id": cur.lastrowid}


@router.put("/favorites/{fid}")
async def update_favorite_terminal(fid: int, body: FavoriteTerminal):
    name, path = body.name.strip(), body.path.strip()
    if not name:
        raise HTTPException(400, "备注不能为空")
    if not path:
        raise HTTPException(400, "文件夹路径不能为空")
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE favorite_terminals SET name=?, path=? WHERE id=?",
            (name, path, fid),
        )
        await db.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "常用终端不存在")
    return {"ok": True}


@router.delete("/favorites/{fid}")
async def delete_favorite_terminal(fid: int):
    async with get_db() as db:
        await db.execute("DELETE FROM favorite_terminals WHERE id=?", (fid,))
        await db.commit()
    return {"ok": True}


@router.post("/favorites/{fid}/open")
async def open_favorite_terminal(fid: int):
    """在常用终端配置的文件夹路径下打开一个新的外部终端窗口"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM favorite_terminals WHERE id=?", (fid,)
        )
    if not rows:
        raise HTTPException(404, "常用终端不存在")
    fav = dict(rows[0])
    terminal_name = open_terminal_at(fav["path"])
    if not terminal_name:
        raise HTTPException(
            400,
            f"无法打开外部终端：目录 {fav['path']} 不存在，或本机未检测到可用的终端模拟器",
        )
    return {"ok": True, "terminal": terminal_name, "path": fav["path"]}


# ════════════════════════════════════════════════════════════════
# 项目终端运行管理（服务配置 + 启动/停止 + 端口监控）
# ════════════════════════════════════════════════════════════════

# 运行中的服务进程：service_id -> subprocess.Popen
_running_services: dict[int, subprocess.Popen] = {}


class ServiceConfigIn(BaseModel):
    name: str
    remark: str = ""
    workdir: str = ""
    commands: list[str] = []
    ports: list[int] = []
    auto_start: bool = False
    enabled: bool = True


def _row_to_service(row) -> dict:
    d = dict(row)
    try:
        d["commands"] = json.loads(d.get("commands") or "[]")
    except Exception:
        d["commands"] = []
    try:
        d["ports"] = [int(p) for p in json.loads(d.get("ports") or "[]")]
    except Exception:
        d["ports"] = []
    d["auto_start"] = bool(d.get("auto_start"))
    d["enabled"] = bool(d.get("enabled"))
    return d


@router.get("/services")
async def list_services():
    """列出所有项目终端运行管理服务配置"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs ORDER BY id ASC"
        )
    return [_row_to_service(r) for r in rows]


@router.get("/services/{sid}")
async def get_service(sid: int):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs WHERE id=?", (sid,)
        )
    if not rows:
        raise HTTPException(404, "服务不存在")
    return _row_to_service(rows[0])


@router.post("/services")
async def create_service(body: ServiceConfigIn):
    """新增一个项目终端运行管理服务配置"""
    await _validate_unique_name(None, body.name)
    commands = json.dumps([c for c in body.commands if c.strip()], ensure_ascii=False)
    ports = json.dumps([int(p) for p in body.ports if str(p).strip()], ensure_ascii=False)
    async with get_db() as db:
        cur = await db.execute(
            """INSERT INTO service_configs
               (name, remark, workdir, commands, ports, auto_start, enabled, updated_at)
               VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (body.name, body.remark, body.workdir, commands, ports,
             int(body.auto_start), int(body.enabled)),
        )
        await db.commit()
        sid = cur.lastrowid
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs WHERE id=?", (sid,)
        )
    return _row_to_service(rows[0])


@router.put("/services/{sid}")
async def update_service(sid: int, body: ServiceConfigIn):
    """更新服务配置（仅在未运行时可改启动步骤/端口）"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs WHERE id=?", (sid,)
        )
        if not rows:
            raise HTTPException(404, "服务不存在")
        await _validate_unique_name(sid, body.name)
        commands = json.dumps([c for c in body.commands if c.strip()], ensure_ascii=False)
        ports = json.dumps([int(p) for p in body.ports if str(p).strip()], ensure_ascii=False)
        await db.execute(
            """UPDATE service_configs SET
               name=?, remark=?, workdir=?, commands=?, ports=?,
               auto_start=?, enabled=?, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (body.name, body.remark, body.workdir, commands, ports,
             int(body.auto_start), int(body.enabled), sid),
        )
        await db.commit()
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs WHERE id=?", (sid,)
        )
    return _row_to_service(rows[0])


@router.delete("/services/{sid}")
async def delete_service(sid: int):
    """删除服务配置（运行中则先停止）"""
    proc = _running_services.pop(sid, None)
    if proc:
        _terminate_proc(proc)
    async with get_db() as db:
        await db.execute("DELETE FROM service_configs WHERE id=?", (sid,))
        await db.commit()
    return {"ok": True}


async def _validate_unique_name(sid: int | None, name: str):
    async with get_db() as db:
        if sid is None:
            rows = await db.execute_fetchall(
                "SELECT id FROM service_configs WHERE name=?", (name,)
            )
        else:
            rows = await db.execute_fetchall(
                "SELECT id FROM service_configs WHERE name=? AND id!=?", (name, sid)
            )
    if rows:
        raise HTTPException(400, f"服务名称已存在：{name}")


def _terminate_proc(proc: subprocess.Popen):
    """终止整个进程组（含子进程）"""
    try:
        if proc.poll() is None:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=8)
            except Exception:
                os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


@router.post("/services/{sid}/start")
async def start_service(sid: int):
    """按配置的步骤顺序启动服务（在工作目录下执行命令步骤）"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs WHERE id=?", (sid,)
        )
        if not rows:
            raise HTTPException(404, "服务不存在")
        svc = _row_to_service(rows[0])

    if not svc["enabled"]:
        raise HTTPException(400, "服务已禁用，请先启用")
    if not svc["commands"]:
        raise HTTPException(400, "未配置启动命令步骤")
    if sid in _running_services and _running_services[sid].poll() is None:
        raise HTTPException(400, "服务已在运行")

    workdir = os.path.expanduser(svc["workdir"]) if svc["workdir"] else None
    if workdir and not os.path.isdir(workdir):
        raise HTTPException(400, f"工作目录不存在：{workdir}")

    # 把多条命令步骤按顺序拼成一个 shell 脚本执行，保证彼此顺序与日志连续
    script = "\n".join(svc["commands"])
    proc = subprocess.Popen(
        ["/bin/bash", "-c", script],
        cwd=workdir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # 独立的进程组，便于整体停止
        env=dict(os.environ),
    )
    _running_services[sid] = proc
    # 等待片刻，确认进程未立即退出（命令本身合法）
    await asyncio.sleep(0.6)
    if proc.poll() is not None:
        _running_services.pop(sid, None)
        raise HTTPException(400, f"服务启动后立即退出（退出码 {proc.returncode}），请检查启动命令")
    return {"ok": True, "pid": proc.pid, "running": True}


@router.post("/services/{sid}/stop")
async def stop_service(sid: int):
    """停止运行中的服务（终止进程组）"""
    proc = _running_services.pop(sid, None)
    if not proc:
        return {"ok": True, "running": False, "message": "服务未在后台运行"}
    _terminate_proc(proc)
    return {"ok": True, "running": False}


@router.get("/services/{sid}/status")
async def service_status(sid: int):
    """返回服务运行状态 + 各配置端口是否在监听"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs WHERE id=?", (sid,)
        )
        if not rows:
            raise HTTPException(404, "服务不存在")
        svc = _row_to_service(rows[0])

    proc = _running_services.get(sid)
    process_alive = proc is not None and proc.poll() is None
    if not process_alive:
        _running_services.pop(sid, None)

    listening = set()
    try:
        ports_info = await get_listening_ports()
        listening = {int(p["port"]) for p in ports_info}
    except Exception:
        pass

    port_status = []
    for p in svc["ports"]:
        port_status.append({
            "port": p,
            "listening": p in listening,
            "monitored": True,
        })
    # 若进程存活但没配端口，则视为运行中；端口是辅助监控
    running = process_alive or (bool(listening & set(svc["ports"])) if svc["ports"] else process_alive)

    return {
        "id": sid,
        "process_alive": process_alive,
        "pid": proc.pid if process_alive else None,
        "running": running,
        "ports": port_status,
    }


@router.get("/services/status/all")
async def all_service_status():
    """批量返回所有服务的运行状态与端口监控"""
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM service_configs ORDER BY id ASC"
        )
        services = [_row_to_service(r) for r in rows]

    listening = set()
    try:
        ports_info = await get_listening_ports()
        listening = {int(p["port"]) for p in ports_info}
    except Exception:
        pass

    result = []
    for svc in services:
        proc = _running_services.get(svc["id"])
        process_alive = proc is not None and proc.poll() is None
        if not process_alive:
            _running_services.pop(svc["id"], None)
        port_status = [
            {"port": p, "listening": p in listening, "monitored": True}
            for p in svc["ports"]
        ]
        running = process_alive or (
            bool(listening & set(svc["ports"])) if svc["ports"] else process_alive
        )
        result.append({
            "id": svc["id"],
            "name": svc["name"],
            "process_alive": process_alive,
            "pid": proc.pid if process_alive else None,
            "running": running,
            "ports": port_status,
        })
    return result
