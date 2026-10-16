"""M8 SSH 管理 路由"""

import os
import shlex
import shutil
import subprocess
import tempfile
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db
from services.ssh_secret import decrypt_secret, encrypt_secret

router = APIRouter()


class SSHHost(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str = ""
    key_path: str = ""
    jump_host: str = ""
    # 明文口令，落库前加密；空串表示「不修改已保存的口令」
    password: str = ""
    # 置 True 表示清除已保存的口令
    clear_password: bool = False


@router.get("/hosts")
async def list_hosts():
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM ssh_hosts ORDER BY id")
    result = []
    for r in rows:
        d = dict(r)
        # 口令密文不下发到前端，只告诉前端有没有存
        d.pop("password", None)
        d["has_password"] = bool(r["password"])
        # 添加状态
        d["status"] = await _check_status(d["host"], d["port"])
        result.append(d)
    return result


@router.post("/hosts")
async def create_host(body: SSHHost):
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO ssh_hosts (name, host, port, username, key_path, jump_host, password) "
            "VALUES (?,?,?,?,?,?,?)",
            (body.name, body.host, body.port, body.username, body.key_path, body.jump_host,
             encrypt_secret(body.password)),
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
        if body.clear_password:
            await db.execute("UPDATE ssh_hosts SET password='' WHERE id=?", (hid,))
        elif body.password:
            await db.execute("UPDATE ssh_hosts SET password=? WHERE id=?",
                             (encrypt_secret(body.password), hid))
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
    """一键连接——在 M4 新开终端执行 ssh（密码登录用 sshpass 自动填）"""
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT * FROM ssh_hosts WHERE id=?", (hid,))
        if not row:
            raise HTTPException(404, "Host not found")
    h = row[0]
    target = f"{h['username']}@{h['host']}" if h['username'] else h['host']
    args: list[str] = ["ssh", shlex.quote(target)]
    if h['port'] != 22:
        args += ["-p", str(int(h['port']))]
    if h['key_path']:
        args += ["-i", shlex.quote(h['key_path'])]
    if h['jump_host']:
        args += ["-J", shlex.quote(h['jump_host'])]

    pw = decrypt_secret(h['password'] or "")
    if pw:
        if not shutil.which("sshpass"):
            raise HTTPException(
                400,
                "未安装 sshpass，请先在依赖检查里安装（系统设置 → 依赖管理），或执行：sudo apt install -y sshpass"
            )
        # 密码写 0600 临时文件，sshpass -f 从文件读，避免出现在进程参数里
        fd, pwfile = tempfile.mkstemp(prefix="dash-ssh-", suffix=".pw")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(pw)
        except Exception:
            os.close(fd)
            raise
        os.chmod(pwfile, 0o600)
        args = ["sshpass", "-f", shlex.quote(pwfile)] + args + [
            "-o", "StrictHostKeyChecking=accept-new"
        ]
        ssh_cmd = " ".join(args) + f"; rm -f {shlex.quote(pwfile)}"
        auth = "password"
    else:
        ssh_cmd = " ".join(args)
        auth = "key" if h['key_path'] else "default"

    from services.pty_manager import pty_manager
    sid = pty_manager.create(f"ssh:{h['name']}", "~", "/bin/bash", ssh_cmd)
    return {"terminal_id": sid, "command": ssh_cmd, "auth": auth}


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
