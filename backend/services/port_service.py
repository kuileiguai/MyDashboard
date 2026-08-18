"""M3 端口采集服务"""

import os
import subprocess
import json
import psutil
from pathlib import Path
from typing import Any


async def get_listening_ports() -> list[dict]:
    """解析 ss -tlnp 获取监听端口列表，pid 缺失时用 /proc/net/tcp fallback"""
    result = []
    for sscmd in (["ss", "-tlnp", "--no-header"], ["ss", "-ulnp", "--no-header"]):
        try:
            proc = subprocess.run(sscmd, capture_output=True, text=True, timeout=5)
            for line in proc.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                info = _parse_ss_line(line)
                if info:
                    result.append(info)
        except Exception:
            pass

    # 对 pid=0 的端口尝试 /proc/net/tcp inode 反查
    inode_map = _build_inode_pid_map()
    if inode_map:
        proc_map = _parse_proc_net()
        for item in result:
            if item["pid"]:
                continue
            key = (item["port"], item["protocol"])
            if key in proc_map:
                inode = proc_map[key]
                item["pid"] = inode_map.get(inode, 0)
                if item["pid"]:
                    _enrich_from_proc(item)
    return result


def _parse_proc_net() -> dict:
    """解析 /proc/net/tcp 和 tcp6，返回 {(port, 'TCP'/'UDP'): inode}"""
    result = {}
    for path, proto in (("/proc/net/tcp", "TCP"), ("/proc/net/tcp6", "TCP"),
                        ("/proc/net/udp", "UDP"), ("/proc/net/udp6", "UDP")):
        try:
            with open(path) as f:
                f.readline()  # skip header
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    st = parts[3]
                    # TCP LISTEN=0A，UDP UNCONN=07
                    listen_states = {"0A"} if proto == "TCP" else {"07"}
                    if st not in listen_states:
                        continue
                    local = parts[1]
                    # 格式 ip:port，均为十六进制
                    try:
                        ip_hex, port_hex = local.rsplit(":", 1)
                        port = int(port_hex, 16)
                    except ValueError:
                        continue
                    inode = parts[9]
                    result[(port, proto)] = inode
        except Exception:
            continue
    return result


def _build_inode_pid_map() -> dict:
    """扫描 /proc/*/fd，建立 {inode: pid} 映射"""
    result = {}
    for pid_dir in os.listdir("/proc"):
        if not pid_dir.isdigit():
            continue
        fd_dir = f"/proc/{pid_dir}/fd"
        try:
            for fd in os.listdir(fd_dir):
                try:
                    link = os.readlink(f"{fd_dir}/{fd}")
                    if link.startswith("socket:["):
                        inode = link[8:-1]
                        result[inode] = int(pid_dir)
                except Exception:
                    continue
        except Exception:
            continue
    return result


def _enrich_from_proc(item: dict):
    """用 /proc 和 psutil 补充进程名/命令/工作目录"""
    pid = item.get("pid", 0)
    if not pid:
        return
    try:
        cmdline = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", errors="replace").replace("\x00", " ").strip()
        cwd = os.readlink(f"/proc/{pid}/cwd")
        item["command"] = cmdline[:200]
        item["cwd"] = cwd
    except Exception:
        pass
    try:
        item["process_name"] = psutil.Process(pid).name()
    except Exception:
        pass


def _parse_ss_line(line: str) -> dict | None:
    """解析 ss 输出行
    ss 列格式: State Recv-Q Send-Q Local Peer [Users]
    Local 是第 4 列 (index 3)，Peer 是第 5 列 (index 4)
    """
    parts = line.split()
    if len(parts) < 4:
        return None
    proto = parts[0].upper()
    if proto not in ("LISTEN", "UNCONN"):
        return None
    local = parts[3]  # Local 地址（如 127.0.0.1:8080 或 [::]:80）
    port = local.rsplit(":", 1)[-1]
    try:
        port_int = int(port)
    except ValueError:
        return None

    pid_str = ""
    proc_name = ""
    if "users:" in line and len(parts) >= 6:
        users = " ".join(parts[5:])
        if "pid=" in users:
            pid_str = users.split("pid=")[-1].split(",")[0].rstrip(")")
        else:
            import re
            m = re.search(r'\(\(["\']([^"\']+)["\'],\s*(\d+)', users)
            if m:
                proc_name = m.group(1)
                pid_str = m.group(2)

    pid = int(pid_str) if pid_str else 0

    # Enrich from /proc and psutil
    cmdline = ""
    cwd = ""
    if pid > 0:
        try:
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read().decode("utf-8", errors="replace").replace("\x00", " ").strip()
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except Exception:
            pass
        if not proc_name:
            try:
                proc_name = psutil.Process(pid).name()
            except Exception:
                pass

    return {
        "port": port_int,
        "protocol": proto,
        "state": parts[1] if len(parts) > 1 else "",
        "pid": pid,
        "process_name": proc_name,
        "command": cmdline[:200],
        "cwd": cwd,
    }


async def get_port_detail(port: int) -> list[dict]:
    """获取某端口的详细信息（含父进程链）"""
    all_ports = await get_listening_ports()
    result = []
    for p in all_ports:
        if p["port"] == port:
            detail = dict(p)
            if p["pid"]:
                detail["parent_chain"] = _get_parent_chain(p["pid"])
                try:
                    proc = psutil.Process(p["pid"])
                    detail["start_time"] = proc.create_time()
                    detail["username"] = proc.username()
                except Exception:
                    detail["start_time"] = None
                    detail["username"] = None
            result.append(detail)
    return result


def _get_parent_chain(pid: int) -> list[dict]:
    chain = []
    visited = set()
    while pid > 0 and pid not in visited:
        visited.add(pid)
        try:
            proc = psutil.Process(pid)
            chain.append({"pid": pid, "name": proc.name(), "cmdline": " ".join(proc.cmdline()[:3])[:200]})
            pid = proc.ppid()
        except Exception:
            break
    return chain


async def kill_process(pid: int, sig: str = "term"):
    try:
        sig_num = 9 if sig == "kill" else 15
        os.kill(pid, sig_num)
        return {"ok": True, "signal": sig_num}
    except ProcessLookupError:
        return {"ok": False, "error": "Process not found"}
    except PermissionError:
        return {"ok": False, "error": "Permission denied"}


async def get_all_processes(sort: str = "cpu", q: str = "") -> list[dict]:
    result = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "cmdline", "username", "status"]):
        try:
            info = proc.info
            if q and q.lower() not in info["name"].lower() and q.lower() not in " ".join(info["cmdline"] or []).lower():
                continue
            result.append({
                "pid": info["pid"],
                "name": info["name"],
                "cpu_percent": info["cpu_percent"] or 0,
                "memory_percent": round(info["memory_percent"] or 0, 2),
                "cmdline": " ".join(info["cmdline"] or [])[:200],
                "username": info["username"],
                "status": info["status"],
            })
        except Exception:
            continue
    key = "cpu_percent" if sort == "cpu" else "memory_percent"
    result.sort(key=lambda x: x[key], reverse=True)
    return result[:200]


async def get_systemd_services(scope: str = "user") -> list[dict]:
    """列出 systemd 服务（scope: user / system）"""
    result = []
    try:
        args = ["systemctl", "list-units", "--type=service", "--no-legend", "--no-pager"]
        if scope == "user":
            args.insert(0, "--user")
        proc = subprocess.run(args, capture_output=True, text=True, timeout=5)
        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 4:
                result.append({
                    "name": parts[0],
                    "load": parts[1],
                    "active": parts[2],
                    "sub": parts[3],
                    "scope": scope,
                })
    except Exception:
        pass
    return result


async def systemd_action(service_name: str, action: str, scope: str = "user") -> dict:
    """M3-F9: 执行 systemd 操作（start/stop/restart/enable/disable）"""
    valid_actions = {"start", "stop", "restart", "enable", "disable", "reload"}
    if action not in valid_actions:
        return {"ok": False, "error": f"Invalid action: {action}. Must be one of {valid_actions}"}
    try:
        args = ["systemctl", action, service_name]
        if scope == "user":
            args.insert(0, "--user")
        proc = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
            "returncode": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Command timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def detect_zombies() -> list[dict]:
    """M3-F10: 识别僵尸进程 (status=zombie) 和疑似孤儿进程 (ppid=1)"""
    zombies = []
    orphans = []
    for proc in psutil.process_iter(["pid", "name", "status", "ppid", "cmdline", "username",
                                      "create_time", "memory_info"]):
        try:
            info = proc.info
            if info["status"] == "zombie":
                zombies.append({
                    "pid": info["pid"], "name": info["name"],
                    "status": "zombie", "ppid": info["ppid"],
                    "cmdline": " ".join(info["cmdline"] or [])[:200],
                    "username": info["username"],
                })
            elif info["ppid"] == 1 and info["pid"] > 2:
                system_names = {"systemd", "dbus-daemon", "polkitd", "accounts-daemon",
                                "rsyslogd", "cron", "sshd", "NetworkManager"}
                if info["name"] not in system_names:
                    orphans.append({
                        "pid": info["pid"], "name": info["name"],
                        "status": "orphan_suspect", "ppid": 1,
                        "cmdline": " ".join(info["cmdline"] or [])[:200],
                        "username": info["username"],
                    })
        except Exception:
            continue
    return {"zombies": zombies, "orphan_suspects": orphans,
            "zombie_count": len(zombies), "orphan_count": len(orphans)}
