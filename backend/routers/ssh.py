"""M8 SSH 管理 路由"""

import subprocess
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db

router = APIRouter()


class SSHHost(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str = ""
    key_path: str = ""
    jump_host: str = ""


@router.get("/hosts")
async def list_hosts():
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM ssh_hosts ORDER BY id")
    result = []
    for r in rows:
        d = dict(r)
        # 添加状态
        d["status"] = await _check_status(d["host"], d["port"])
        result.append(d)
    return result


@router.post("/hosts")
async def create_host(body: SSHHost):
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO ssh_hosts (name, host, port, username, key_path, jump_host) VALUES (?,?,?,?,?,?)",
            (body.name, body.host, body.port, body.username, body.key_path, body.jump_host),
        )
        await db.commit()
        return {"id": cur.lastrowid}


@router.put("/hosts/{hid}")
async def update_host(hid: int, body: SSHHost):
    async with get_db() as db:
        await db.execute(
            "UPDATE ssh_hosts SET name=?,host=?,port=?,username=?,key_path=?,jump_host=? WHERE id=?",
            (body.name, body.host, body.port, body.username, body.key_path, body.jump_host, hid),
        )
        await db.commit()
    return {"ok": True}


@router.delete("/hosts/{hid}")
async def delete_host(hid: int):
    async with get_db() as db:
        await db.execute("DELETE FROM ssh_hosts WHERE id=?", (hid,))
        await db.commit()
    return {"ok": True}


@router.post("/hosts/{hid}/connect")
async def connect_host(hid: int):
    """一键连接——在 M4 新开终端执行 ssh"""
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT * FROM ssh_hosts WHERE id=?", (hid,))
        if not row:
            raise HTTPException(404, "Host not found")
    h = row[0]
    cmd = f"ssh {h['username']}@{h['host']}" if h['username'] else f"ssh {h['host']}"
    if h['port'] != 22:
        cmd += f" -p {h['port']}"
    if h['key_path']:
        cmd += f" -i {h['key_path']}"
    if h['jump_host']:
        cmd += f" -J {h['jump_host']}"
    from services.pty_manager import pty_manager
    sid = pty_manager.create(f"ssh:{h['name']}", "~", "/bin/bash", cmd)
    return {"terminal_id": sid, "command": cmd}


# ── M8-F4: 连接状态探测 ──

@router.get("/hosts/{hid}/status")
async def host_status(hid: int):
    """用 ping + 端口探测判断在线状态"""
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT * FROM ssh_hosts WHERE id=?", (hid,))
        if not row:
            raise HTTPException(404, "Host not found")
    h = row[0]
    s = await _check_status(h["host"], h["port"])
    return s


async def _check_status(host: str, port: int) -> dict:
    """ping + TCP 端口探测"""
    import socket
    # Ping
    ping_ok = False
    try:
        proc = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            capture_output=True, text=True, timeout=3,
        )
        ping_ok = proc.returncode == 0
    except Exception:
        pass

    # Port probe
    port_open = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex((host, port))
        port_open = result == 0
        s.close()
    except Exception:
        pass

    if port_open:
        status = "online"
    elif ping_ok:
        status = "ping_only"
    else:
        status = "offline"

    return {"status": status, "ping": ping_ok, "port_open": port_open}


# ── M8-F5: 远程路径收藏 ──

@router.get("/hosts/{hid}/remote-bookmarks")
async def list_remote_bookmarks(hid: int):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM remote_bookmarks WHERE ssh_host_id = ?", (hid,)
        )
    return [dict(r) for r in rows]


class RemoteBookmarkCreate(BaseModel):
    ssh_host_id: int
    name: str
    path: str


@router.post("/remote-bookmarks")
async def create_remote_bookmark(body: RemoteBookmarkCreate):
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO remote_bookmarks (ssh_host_id, name, path) VALUES (?,?,?)",
            (body.ssh_host_id, body.name, body.path),
        )
        await db.commit()
        return {"id": cur.lastrowid}


@router.delete("/remote-bookmarks/{bid}")
async def delete_remote_bookmark(bid: int):
    async with get_db() as db:
        await db.execute("DELETE FROM remote_bookmarks WHERE id = ?", (bid,))
        await db.commit()
    return {"ok": True}


# ── M8-F1: ssh config 解析 ──

@router.get("/config/parse")
async def parse_ssh_config():
    """解析 ~/.ssh/config 并返回主机列表"""
    import os
    config_path = os.path.expanduser("~/.ssh/config")
    hosts = []
    if not os.path.exists(config_path):
        return {"hosts": [], "message": "No ~/.ssh/config found"}
    try:
        with open(config_path) as f:
            current = {}
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                key, val = parts[0].lower(), parts[1]
                if key == "host" and not val.startswith("*"):
                    if current:
                        hosts.append(dict(current))
                    current = {"name": val, "host": val, "port": 22, "username": "", "key_path": "", "jump_host": ""}
                elif key == "hostname":
                    current["host"] = val
                elif key == "port":
                    current["port"] = int(val)
                elif key == "user":
                    current["username"] = val
                elif key == "identityfile":
                    current["key_path"] = val
                elif key == "proxyjump":
                    current["jump_host"] = val
            if current:
                hosts.append(dict(current))
    except Exception as e:
        return {"hosts": [], "error": str(e)}
    return {"hosts": hosts}


@router.post("/config/import")
async def import_ssh_config():
    """从 ~/.ssh/config 一键导入到数据库"""
    data = await parse_ssh_config()
    imported = 0
    async with get_db() as db:
        for h in data.get("hosts", []):
            if not h.get("host"):
                continue
            await db.execute(
                "INSERT INTO ssh_hosts (name, host, port, username, key_path, jump_host) VALUES (?,?,?,?,?,?)",
                (h["name"], h["host"], h.get("port", 22), h.get("username", ""),
                 h.get("key_path", ""), h.get("jump_host", "")),
            )
            imported += 1
        await db.commit()
    return {"ok": True, "imported": imported, "hosts": data.get("hosts", [])}
