"""M3 端口采集服务"""

import os
import re
import time
import socket
import asyncio
import subprocess
import json
import psutil
from pathlib import Path
from typing import Any

from database import get_db

# ── 端口配置（关注端口 / 自动快照 / 告警开关）──

DEFAULT_WATCH_PORTS = [22, 80, 443, 3000, 5000, 5432, 6379, 8000, 8080, 8443, 9090, 27017]
SNAPSHOT_KEEP = 100  # 只保留最近 N 条快照

_CFG_KEYS = {
    "watch_ports": "port_watch_ports",
    "auto_snapshot": "port_auto_snapshot",
    "interval_min": "port_auto_interval_min",
    "alert_new": "port_alert_new",
    "alert_gone": "port_alert_gone",
    "auto_last": "port_auto_last",
}


def _fmt_ts(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""


async def _get_setting(key: str) -> str:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else ""


async def _set_setting(key: str, value: str) -> None:
    async with get_db() as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()


async def load_port_config() -> dict:
    cfg = {}
    for name, key in _CFG_KEYS.items():
        cfg[name] = await _get_setting(key)
    try:
        watch = json.loads(cfg["watch_ports"] or "[]")
    except Exception:
        watch = []
    watch = [int(x) for x in watch if str(x).strip().isdigit()]
    auto_last = 0.0
    try:
        auto_last = float(cfg["auto_last"] or 0)
    except ValueError:
        auto_last = 0.0
    return {
        "watch_ports": watch or list(DEFAULT_WATCH_PORTS),
        "auto_snapshot": cfg["auto_snapshot"] == "1",
        "interval_min": int(cfg["interval_min"] or 30) if str(cfg["interval_min"] or "").isdigit() else 30,
        "alert_new": cfg["alert_new"] != "0",
        "alert_gone": cfg["alert_gone"] != "0",
        "auto_last": auto_last,
        "auto_last_human": _fmt_ts(auto_last),
    }


async def save_port_config(body: dict) -> dict:
    if "watch_ports" in body and body["watch_ports"] is not None:
        watch = []
        for x in body["watch_ports"]:
            try:
                watch.append(int(str(x).strip()))
            except (TypeError, ValueError):
                continue
        await _set_setting(_CFG_KEYS["watch_ports"], json.dumps(sorted(set(watch))))
    if "auto_snapshot" in body and body["auto_snapshot"] is not None:
        await _set_setting(_CFG_KEYS["auto_snapshot"], "1" if body["auto_snapshot"] else "0")
    if "interval_min" in body and body["interval_min"] is not None:
        try:
            interval = max(1, min(720, int(body["interval_min"])))
        except (TypeError, ValueError):
            interval = 30
        await _set_setting(_CFG_KEYS["interval_min"], str(interval))
    if "alert_new" in body and body["alert_new"] is not None:
        await _set_setting(_CFG_KEYS["alert_new"], "1" if body["alert_new"] else "0")
    if "alert_gone" in body and body["alert_gone"] is not None:
        await _set_setting(_CFG_KEYS["alert_gone"], "1" if body["alert_gone"] else "0")
    return await load_port_config()


# ── 端口备注（按 端口/状态 记，如 8080/LISTEN）──

async def load_port_remarks() -> dict:
    raw = await _get_setting("port_remarks")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def save_port_remark(key: str, remark: str) -> dict:
    remarks = await load_port_remarks()
    if (remark or "").strip():
        remarks[key] = remark.strip()[:60]
    else:
        remarks.pop(key, None)
    await _set_setting("port_remarks", json.dumps(remarks, ensure_ascii=False))
    return remarks


# ── 端口快照 + 变化告警 ──

async def list_snapshots(limit: int = 50) -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, created_at, snapshot_data FROM port_snapshots ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        try:
            data = json.loads(r["snapshot_data"])
        except Exception:
            data = {}
        out.append({"id": r["id"], "created_at": r["created_at"], "ts": data.get("ts", 0),
                    "source": data.get("source", ""), "count": len(data.get("ports", [])),
                    "data": data})
    return out


async def take_snapshot(source: str = "manual") -> dict:
    """保存当前端口快照，并与上一条快照对比生成告警"""
    ports = await get_listening_ports()
    snap = {"ts": time.time(), "source": source, "ports": ports}
    async with get_db() as db:
        cur = await db.execute("INSERT INTO port_snapshots (snapshot_data) VALUES (?)",
                               (json.dumps(snap),))
        snap_id = cur.lastrowid
        prev = await db.execute_fetchall(
            "SELECT id, snapshot_data FROM port_snapshots WHERE id < ? ORDER BY id DESC LIMIT 1", (snap_id,))
        await db.execute(
            "DELETE FROM port_snapshots WHERE id NOT IN "
            "(SELECT id FROM port_snapshots ORDER BY id DESC LIMIT ?)", (SNAPSHOT_KEEP,))
        await db.commit()

    new_ports, gone_ports, alerts = [], [], []
    if prev:
        try:
            prev_data = json.loads(prev[0]["snapshot_data"])
        except Exception:
            prev_data = {}
        prev_map = {(p.get("port"), p.get("protocol")): p for p in prev_data.get("ports", [])}
        cur_map = {(p.get("port"), p.get("protocol")): p for p in ports}
        new_ports = [p for k, p in cur_map.items() if k not in prev_map]
        gone_ports = [p for k, p in prev_map.items() if k not in cur_map]
        alerts = await _record_alerts(snap_id, new_ports, gone_ports, source)

    return {
        "id": snap_id, "ts": snap["ts"], "source": source, "count": len(ports),
        "new_ports": new_ports, "gone_ports": gone_ports, "alerts": len(alerts),
        "ports": ports,
    }


async def _record_alerts(snap_id: int, new_ports: list[dict], gone_ports: list[dict],
                         source: str) -> list[dict]:
    cfg = await load_port_config()
    watch = set(cfg["watch_ports"])
    rows = []
    tag = "自动快照" if source == "auto" else "手动快照"
    if cfg["alert_new"]:
        for p in new_ports:
            port = p.get("port", 0)
            watched = port in watch
            exposed = bool(p.get("exposed"))
            if exposed:
                severity = "danger" if not watched else "warning"
                msg = f"{tag}：新增对外监听端口 {port}/{p.get('protocol', '')}（{p.get('address') or '全部网卡'}）· {p.get('process_name') or '未知进程'}"
            else:
                severity = "warning" if watched else "info"
                msg = f"{tag}：新增端口 {port}/{p.get('protocol', '')} · {p.get('process_name') or '未知进程'}"
            rows.append(("new_port", severity, port, p.get("protocol", ""),
                         p.get("process_name", ""), msg, snap_id))
    if cfg["alert_gone"]:
        for p in gone_ports:
            port = p.get("port", 0)
            severity = "warning" if port in watch else "info"
            msg = f"{tag}：端口 {port}/{p.get('protocol', '')} 已消失 · 原进程 {p.get('process_name') or '未知'}"
            rows.append(("gone_port", severity, port, p.get("protocol", ""),
                         p.get("process_name", ""), msg, snap_id))

    if not rows:
        return []
    async with get_db() as db:
        await db.executemany(
            "INSERT INTO port_alerts (alert_type, severity, port, protocol, process_name, message, snapshot_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        await db.commit()
    return rows


async def list_alerts(limit: int = 100, unread_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM port_alerts"
    if unread_only:
        sql += " WHERE is_read = 0"
    sql += " ORDER BY id DESC LIMIT ?"
    async with get_db() as db:
        rows = await db.execute_fetchall(sql, (limit,))
        cnt = await db.execute_fetchall("SELECT COUNT(*) as c FROM port_alerts WHERE is_read = 0")
    return {
        "alerts": [dict(r) for r in rows],
        "unread": cnt[0]["c"] if cnt else 0,
    }


async def mark_alerts_read(ids: list[int] | None = None, all_read: bool = False) -> dict:
    async with get_db() as db:
        if all_read or not ids:
            cur = await db.execute("UPDATE port_alerts SET is_read = 1 WHERE is_read = 0")
        else:
            marks = ",".join("?" * len(ids))
            cur = await db.execute(f"UPDATE port_alerts SET is_read = 1 WHERE id IN ({marks})", tuple(ids))
        await db.commit()
    return {"ok": True, "updated": cur.rowcount if cur else 0}


async def clear_alerts(ids: list[int] | None = None, all_clear: bool = False) -> dict:
    async with get_db() as db:
        if all_clear or not ids:
            cur = await db.execute("DELETE FROM port_alerts")
        else:
            marks = ",".join("?" * len(ids))
            cur = await db.execute(f"DELETE FROM port_alerts WHERE id IN ({marks})", tuple(ids))
        await db.commit()
    return {"ok": True, "removed": cur.rowcount if cur else 0}


async def port_auto_snapshot_loop():
    """后台定时快照任务：每 60s 检查一次是否到了自动快照时间"""
    while True:
        try:
            await asyncio.sleep(60)
            cfg = await load_port_config()
            if not cfg["auto_snapshot"]:
                continue
            if time.time() - cfg["auto_last"] < max(1, cfg["interval_min"]) * 60:
                continue
            await take_snapshot("auto")
            await _set_setting(_CFG_KEYS["auto_last"], str(time.time()))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


async def get_listening_ports() -> list[dict]:
    """解析 ss -tlnp 获取监听端口列表，pid 缺失时用 /proc/net/tcp fallback"""
    result = []
    for family, sscmd in (("tcp", ["ss", "-tlnp", "--no-header"]),
                          ("udp", ["ss", "-ulnp", "--no-header"])):
        try:
            proc = subprocess.run(sscmd, capture_output=True, text=True, timeout=5)
            for line in proc.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                info = _parse_ss_line(line, family)
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

    _enrich_network(result)
    return result


# ── 监听地址 / 网卡 / 对外暴露 / 容器归属 ──

_EXPOSED_ADDRS = {"", "*", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}
_LOCAL_ADDRS = {"127.0.0.1", "::1", "0:0:0:0:0:0:0:1"}
_CGROUP_RE = re.compile(
    r"(?:docker|crio|libpod|containerd|kubepods)[-/]([0-9a-f]{12,64})", re.I)
# 镜像 docker ps 的 Ports 字段，把 `0.0.0.0:8080->80/tcp` / `[::]:80->80/tcp` /
# `0.0.0.0:27010-27011->27010-27011/tcp` / `32020/tcp`(仅容器端口) 都识别出来
_DOCKER_PORT_RE = re.compile(
    r"^(?:\[?([0-9a-fA-F:.]+)\]?:((?:\d+|\d+-\d+))->)?((?:\d+|\d+-\d+))/(tcp|udp)$", re.I)
_docker_cache: dict = {"ts": 0.0, "names": {}}
_docker_port_cache: dict = {"ts": 0.0, "ports": {}}


def _clean_addr(addr: str) -> str:
    a = (addr or "").strip()
    if a.startswith("[") and a.endswith("]"):
        a = a[1:-1]
    return a


def _iface_map() -> dict[str, str]:
    """{ip: 网卡名}，用于把监听地址映射到网卡"""
    mapping: dict[str, str] = {}
    try:
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family in (socket.AF_INET, socket.AF_INET6):
                    mapping[_clean_addr(a.address)] = name
    except Exception:
        pass
    return mapping


def _container_id_of(pid: int) -> str:
    """从 /proc/<pid>/cgroup 里提取容器 ID（docker / containerd / podman / k8s）"""
    if not pid:
        return ""
    try:
        with open(f"/proc/{pid}/cgroup") as f:
            text = f.read()
    except OSError:
        return ""
    for line in text.splitlines():
        m = _CGROUP_RE.search(line)
        if m:
            return m.group(1)[:12]
    return ""


def _docker_container_names() -> dict[str, str]:
    """{容器短 ID: 容器名}，60 秒缓存，docker 不可用时返回空"""
    now = time.time()
    if now - _docker_cache["ts"] < 60:
        return _docker_cache["names"]
    names: dict[str, str] = {}
    try:
        proc = subprocess.run(["docker", "ps", "--format", "{{.ID}}\t{{.Names}}"],
                              capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    names[parts[0][:12]] = parts[1]
    except Exception:
        pass
    _docker_cache["ts"] = now
    _docker_cache["names"] = names
    return names


def _enrich_network(items: list[dict]) -> None:
    """补充 网卡 / 对外暴露标记 / 容器归属
    两路查找：
      1) 进程 cgroup → 容器 ID → 容器名（适用于 root 权限下能看到 PID 的场景）
      2) docker ps 的端口映射（host_ip+host_port → 容器名），不依赖 PID，
         因此对「非 root 后端看不到 docker-proxy / 容器进程在另一网络命名空间」的场景也能补上
    """
    iface_map = _iface_map()
    cid_items: dict[str, list[dict]] = {}
    for item in items:
        addr = item.get("address", "")
        if item.get("exposed"):
            item["iface"] = "全部网卡"
        else:
            item["iface"] = iface_map.get(addr, "")
        cid = _container_id_of(item.get("pid", 0))
        if cid:
            item["container_id"] = cid
            cid_items.setdefault(cid, []).append(item)
    if cid_items:
        names = _docker_container_names()
        for cid, group in cid_items.items():
            for item in group:
                item["container_name"] = names.get(cid, "")

    # 兜底：docker port map（关键路径，处理「端口在宿主机 ss 中体现为 docker-proxy」的情况）
    if any(not item.get("container_name") for item in items):
        port_map = _docker_port_map()
        for item in items:
            if item.get("container_name"):
                continue
            proto = (item.get("family") or "").upper()
            port = item.get("port", 0)
            if not proto or not port:
                continue
            if item.get("exposed"):
                # `*`/`0.0.0.0`/`::` 都是「全部网卡」，要同时试 IPv4 和 IPv6 的发布
                candidates = [("0.0.0.0", port, proto), ("::", port, proto)]
            else:
                candidates = [(item.get("address", ""), port, proto)]
            for key in candidates:
                name = port_map.get(key)
                if name:
                    item["container_name"] = name
                    break


def _docker_port_map() -> dict[tuple, str]:
    """{(host_ip, host_port, proto): container_name}，60s 缓存。
    通过 `docker ps --format '{{.ID}}\\t{{.Names}}\\t{{.Ports}}'` 解析。
    支持单端口 `8080`、端口段 `27010-27011`、仅声明容器端口的条目（跳过）。"""
    now = time.time()
    if now - _docker_port_cache["ts"] < 60:
        return _docker_port_cache["ports"]
    mapping: dict[tuple, str] = {}
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            for line in proc.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) < 3 or not parts[2].strip():
                    continue
                cid, name, ports_str = parts[0], parts[1], parts[2]
                for seg in ports_str.split(","):
                    seg = seg.strip()
                    if not seg:
                        continue
                    m = _DOCKER_PORT_RE.match(seg)
                    if not m:
                        continue
                    host_ip, host_port_s, _container_port_s, proto = m.groups()
                    proto = proto.upper()
                    if not host_ip:
                        # 仅声明了容器端口，没发布到宿主机
                        continue
                    if "-" in host_port_s:
                        a, b = host_port_s.split("-")
                        for p in range(int(a), int(b) + 1):
                            mapping[(host_ip, p, proto)] = name or cid[:12]
                    else:
                        mapping[(host_ip, int(host_port_s), proto)] = name or cid[:12]
    except Exception:
        pass
    _docker_port_cache["ts"] = now
    _docker_port_cache["ports"] = mapping
    return mapping


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


def _parse_ss_line(line: str, family: str = "tcp") -> dict | None:
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
    raw_addr, _, port = local.rpartition(":")
    try:
        port_int = int(port)
    except ValueError:
        return None
    address = _clean_addr(raw_addr)
    exposed = address in _EXPOSED_ADDRS

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
        "family": family,
        "state": parts[1] if len(parts) > 1 else "",
        "address": address,
        "exposed": exposed,
        "iface": "",
        "container_id": "",
        "container_name": "",
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
        # 注意：--user 必须放在子命令之前（systemctl --user list-units），
        # 放在 argv[0] 会把 "--user" 当成要执行的程序，导致 FileNotFoundError
        args = ["systemctl", "list-units", "--type=service", "--no-legend", "--no-pager"]
        if scope == "user":
            args.insert(1, "--user")
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
            args.insert(1, "--user")
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
