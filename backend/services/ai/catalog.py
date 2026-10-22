"""系统配置 Catalog。

把分散在 SQLite / 内存 / CLI 里的配置与状态，聚合成模型可读的结构。
原则：
- 只读、不执行；
- 区分 configured（配置里写的）和 live_status（当前实际状态）；
- 不返回密码/密钥类字段；
- Docker / env 这类慢查询带缓存和超时，失败不影响其他配置。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import config
from database import get_db
from services.ai.redact import redact_obj, redact_text
from services.docker_service import (
    container_inspect,
    container_logs,
    docker_available,
    list_containers,
    verify_compose_projects,
)
from services.monitor_service import get_snapshot
from services.port_service import get_listening_ports

# ── 小工具 ────────────────────────────────────────────────────────

def _json_list(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw or "[]")
        return val if isinstance(val, list) else []
    except Exception:
        return []


def _settings_value(rows, key: str, default: str = "") -> str:
    for r in rows or []:
        if r["key"] == key:
            return r["value"]
    return default


def _loads(raw: str | None, default):
    try:
        return json.loads(raw or "")
    except Exception:
        return default


def _limit_text(value: Any, size: int = 2000) -> str:
    text = str(value or "")
    return text if len(text) <= size else text[:size] + "…"


def _status_text(running: bool | None) -> str:
    if running is True:
        return "running"
    if running is False:
        return "stopped"
    return "unknown"


# ── 缓存 ──────────────────────────────────────────────────────────

_service_cache: dict[str, Any] = {"ts": 0.0, "data": {}}
_docker_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_env_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def invalidate_service_cache() -> None:
    _service_cache["ts"] = 0.0
    _service_cache["data"] = {}


def invalidate_docker_cache() -> None:
    _docker_cache["ts"] = 0.0
    _docker_cache["data"] = None


async def _service_status_map(force: bool = False) -> dict[int, dict]:
    now = time.time()
    if not force and _service_cache["data"] and (now - _service_cache["ts"]) < config.AI_CATALOG_CACHE_TTL:
        return _service_cache["data"]
    data: dict[int, dict] = {}
    try:
        from routers.terminal import all_service_status
        items = await all_service_status()
        for item in items or []:
            try:
                data[int(item["id"])] = item
            except Exception:
                continue
    except Exception:
        data = {}
    _service_cache["ts"] = now
    _service_cache["data"] = data
    return data


# ── 基础读取 ──────────────────────────────────────────────────────

async def service_configs(include_status: bool = True) -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM service_configs ORDER BY id ASC")
    statuses = await _service_status_map() if include_status else {}
    result = []
    for row in rows:
        d = dict(row)
        commands = [redact_text(_limit_text(x, 2000)) for x in _json_list(d.get("commands"))]
        ports = []
        for p in _json_list(d.get("ports")):
            try:
                ports.append(int(p))
            except Exception:
                pass
        st = statuses.get(int(d["id"]), {})
        running = bool(st.get("running")) if st else None
        result.append({
            "id": int(d["id"]),
            "name": d.get("name", ""),
            "remark": redact_text(d.get("remark") or ""),
            "workdir": d.get("workdir") or "",
            "commands": commands,
            "ports": ports,
            "auto_start": bool(d.get("auto_start")),
            "enabled": bool(d.get("enabled")),
            "configured": True,
            "live_status": _status_text(running),
            "process_alive": st.get("process_alive"),
            "pid": st.get("pid"),
            "status_source": "service_status" if st else "unavailable",
        })
    return result


async def service_detail(service_id: int) -> dict:
    items = await service_configs(include_status=True)
    for item in items:
        if item["id"] == int(service_id):
            return item
    raise KeyError(f"服务不存在：{service_id}")


async def projects() -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM projects ORDER BY sort_order, id")
    result = []
    for row in rows:
        d = dict(row)
        result.append({
            "id": int(d["id"]),
            "name": d.get("name", ""),
            "root_path": d.get("root_path") or "",
            "terminal_group": d.get("terminal_group") or "",
            "env_name": d.get("env_name") or "",
            "command_group": d.get("command_group") or "",
            "log_paths": _json_list(d.get("log_paths")),
        })
    return result


async def favorite_terminals() -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, name, path, sort_order FROM favorite_terminals ORDER BY sort_order, id")
    return [{
        "id": int(r["id"]),
        "name": r["name"] or "",
        "path": r["path"] or "",
    } for r in rows]


async def ssh_hosts() -> list[dict]:
    # 显式字段：绝不 SELECT password
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, name, host, port, username, key_path, jump_host, "
            "CASE WHEN password != '' THEN 1 ELSE 0 END AS has_password "
            "FROM ssh_hosts ORDER BY id")
    return [{
        "id": int(r["id"]),
        "name": r["name"] or "",
        "host": r["host"] or "",
        "port": int(r["port"] or 22),
        "username": r["username"] or "",
        "key_path": r["key_path"] or "",
        "jump_host": r["jump_host"] or "",
        "has_password": bool(r["has_password"]),
    } for r in rows]


async def commands_summary() -> dict:
    async with get_db() as db:
        total = await db.execute_fetchall("SELECT COUNT(*) AS c FROM commands")
        cats = await db.execute_fetchall(
            "SELECT category, COUNT(*) AS c FROM commands "
            "WHERE category != '' GROUP BY category ORDER BY c DESC, category ASC")
    return {
        "count": total[0]["c"] if total else 0,
        "categories": [{"name": r["category"], "count": r["c"]} for r in cats],
        "hint": "需要具体命令时用 command_search 工具，不要一次拉全量。",
    }


async def recent_history(limit: int = 5) -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT command, cwd, source, created_at, run_count FROM terminal_history "
            "ORDER BY created_at DESC, id DESC LIMIT ?", (max(1, min(20, limit)),))
    return [{
        "command": redact_text(r["command"] or ""),
        "cwd": r["cwd"] or "",
        "source": r["source"] or "terminal",
        "created_at": r["created_at"],
        "run_count": r["run_count"] or 1,
    } for r in rows]


async def search_commands(query: str = "", limit: int = 10) -> list[dict]:
    limit = max(1, min(50, limit))
    async with get_db() as db:
        if query.strip():
            like = f"%{query.strip()}%"
            rows = await db.execute_fetchall(
                "SELECT id, category, service, scenario, command, description, "
                "params_json, examples_json, is_favorite, use_count FROM commands "
                "WHERE command LIKE ? OR description LIKE ? OR category LIKE ? "
                "OR service LIKE ? OR scenario LIKE ? "
                "ORDER BY is_favorite DESC, use_count DESC, id ASC LIMIT ?",
                (like, like, like, like, like, limit))
        else:
            rows = await db.execute_fetchall(
                "SELECT id, category, service, scenario, command, description, "
                "params_json, examples_json, is_favorite, use_count FROM commands "
                "ORDER BY is_favorite DESC, use_count DESC, id ASC LIMIT ?", (limit,))
    return [{
        "id": int(r["id"]),
        "category": r["category"] or "",
        "service": r["service"] or "",
        "scenario": r["scenario"] or "",
        "command": redact_text(r["command"] or ""),
        "description": redact_text(r["description"] or ""),
        "params": _loads(r["params_json"], []),
        "examples": _loads(r["examples_json"], []),
        "is_favorite": bool(r["is_favorite"]),
        "use_count": r["use_count"] or 0,
        "source": f"commands#{r['id']}",
    } for r in rows]


async def log_sources() -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT key, value FROM settings WHERE key IN ('log_files', 'log_remarks')")
    library = _loads(_settings_value(rows, "log_files", "[]"), [])
    remarks = _loads(_settings_value(rows, "log_remarks", "{}"), {})
    result = []
    for item in library:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        path = item["path"]
        result.append({
            "path": path,
            "remark": redact_text(remarks.get(path, "")),
            "added_at": item.get("added_at", ""),
        })
    return result


async def env_info(force: bool = False) -> dict:
    now = time.time()
    if not force and _env_cache["data"] is not None and (now - _env_cache["ts"]) < config.AI_ENV_CACHE_TTL:
        return _env_cache["data"]

    data: dict
    try:
        from routers.env import env_list
        raw = await asyncio.wait_for(env_list(), timeout=15)
        data = {
            "available": True,
            "python": (raw.get("python") or [])[:10],
            "conda": (raw.get("conda") or [])[:10],
            "node": (raw.get("node") or [])[:10],
            "uv": {
                "venvs_found": ((raw.get("uv") or {}).get("venvs_found") or [])[:10],
                "venv_count": len((raw.get("uv") or {}).get("venvs_found") or []),
            },
            "cuda": raw.get("cuda") or {},
            "java": raw.get("java") or {},
            "go": raw.get("go") or {},
        }
    except asyncio.TimeoutError:
        data = {"available": False, "error": "环境探测超时"}
    except Exception as e:
        data = {"available": False, "error": str(e)}

    _env_cache["ts"] = now
    _env_cache["data"] = data
    return data


# ── Docker ───────────────────────────────────────────────────────

async def docker_info(force: bool = False) -> dict:
    now = time.time()
    if not force and _docker_cache["data"] is not None and (now - _docker_cache["ts"]) < 10:
        return _docker_cache["data"]

    try:
        avail = await asyncio.to_thread(docker_available)
        if not avail.get("available"):
            data = {"available": False, **avail, "containers": [], "compose": []}
        else:
            raw_containers = await asyncio.to_thread(list_containers, True)
            containers = []
            for c in raw_containers or []:
                if not isinstance(c, dict) or "error" in c:
                    continue
                containers.append({
                    "id": c.get("ID") or c.get("Id") or "",
                    "name": c.get("Names") or c.get("Name") or "",
                    "image": c.get("Image") or "",
                    "status": c.get("Status") or "",
                    "state": (c.get("State") or "").lower(),
                    "ports": c.get("Ports") or "",
                })
            async with get_db() as db:
                rows = await db.execute_fetchall(
                    "SELECT value FROM settings WHERE key = 'compose_projects'")
            records = _loads(rows[0]["value"], []) if rows else []
            records = [r for r in records if isinstance(r, dict) and r.get("path")]
            compose = await asyncio.to_thread(verify_compose_projects, records)
            data = {
                "available": True,
                "version": avail.get("version", ""),
                "containers": containers,
                "compose": [{
                    "name": p.get("name", ""),
                    "path": p.get("path", ""),
                    "compose_file": p.get("compose_file", ""),
                    "exists": bool(p.get("exists")),
                    "dir_exists": bool(p.get("dir_exists")),
                } for p in compose],
            }
    except Exception as e:
        data = {"available": False, "error": str(e), "containers": [], "compose": []}

    _docker_cache["ts"] = now
    _docker_cache["data"] = data
    return data


async def docker_detail(container_id: str) -> dict:
    inspect = await asyncio.to_thread(container_inspect, container_id)
    if inspect.get("error"):
        raise KeyError(inspect["error"])
    logs = await asyncio.to_thread(container_logs, container_id, 80)
    state = inspect.get("State") or {}
    config = inspect.get("Config") or {}
    mounts = inspect.get("Mounts") or []
    ports = (inspect.get("NetworkSettings") or {}).get("Ports") or {}
    return {
        "id": inspect.get("Id", container_id),
        "name": (inspect.get("Name") or "").lstrip("/"),
        "image": config.get("Image", ""),
        "state": state.get("Status", ""),
        "exit_code": state.get("ExitCode"),
        "started_at": state.get("StartedAt", ""),
        "finished_at": state.get("FinishedAt", ""),
        "cmd": redact_obj(config.get("Cmd") or []),
        "ports": ports,
        "mounts": [{
            "source": m.get("Source", ""),
            "destination": m.get("Destination", ""),
            "rw": bool(m.get("RW")),
        } for m in mounts],
        "recent_logs": redact_text(_limit_text(logs, 8000)),
        "source": f"docker:{container_id}",
    }


# ── 系统状态 ──────────────────────────────────────────────────────

async def system_snapshot() -> dict:
    snap = await asyncio.to_thread(get_snapshot)
    # 只保留问答需要的字段，避免把整份 150 点历史带进上下文
    gpu = snap.get("gpu") or {}
    return {
        "ts": snap.get("ts"),
        "cpu": snap.get("cpu"),
        "load": snap.get("load"),
        "memory": snap.get("memory"),
        "swap": snap.get("swap"),
        "disks": snap.get("disks"),
        "network": snap.get("network"),
        "gpu": {
            "available": gpu.get("available"),
            "devices": gpu.get("devices") or [],
            "reason": gpu.get("reason", ""),
        },
    }


async def listening_ports(limit: int = 100) -> list[dict]:
    ports = await get_listening_ports()
    result = []
    for p in (ports or [])[:max(1, min(300, limit))]:
        result.append({
            "port": p.get("port"),
            "protocol": p.get("protocol"),
            "address": p.get("address"),
            "pid": p.get("pid"),
            "process_name": p.get("process_name"),
            "command": redact_text(_limit_text(p.get("command"), 500)),
            "cwd": p.get("cwd"),
            "container_name": p.get("container_name", ""),
        })
    return result


# ── 总览 / 详情 ───────────────────────────────────────────────────

DEFAULT_TYPES = ("projects", "services", "commands", "terminals", "ssh", "docker", "logs", "history")


async def catalog_overview(types: list[str] | None = None, include_env: bool = False,
                           compact: bool = False) -> dict:
    selected = set(types or DEFAULT_TYPES)
    services = await service_configs(include_status=True) if "services" in selected else []
    docker = await docker_info() if "docker" in selected else None

    overview: dict[str, Any] = {
        "host": {
            "source": "catalog",
            "note": "configured 表示配置里存在，live_status 表示当前实际状态。",
        },
        "counts": {},
        "services": services,
        "projects": await projects() if "projects" in selected else [],
        "commands": await commands_summary() if "commands" in selected else {},
        "favorite_terminals": await favorite_terminals() if "terminals" in selected else [],
        "ssh_hosts": await ssh_hosts() if "ssh" in selected else [],
        "docker": docker,
        "log_sources": await log_sources() if "logs" in selected else [],
        "recent_history": await recent_history(5) if "history" in selected else [],
    }
    if include_env:
        overview["envs"] = await env_info()

    overview["counts"] = {
        "services": len(overview["services"]),
        "services_running": sum(1 for s in overview["services"] if s.get("live_status") == "running"),
        "projects": len(overview["projects"]),
        "commands": (overview["commands"] or {}).get("count", 0),
        "favorite_terminals": len(overview["favorite_terminals"]),
        "ssh_hosts": len(overview["ssh_hosts"]),
        "containers": len((docker or {}).get("containers") or []),
        "compose_projects": len((docker or {}).get("compose") or []),
        "log_sources": len(overview["log_sources"]),
    }

    if compact:
        # 系统提示只放“对象索引”，详细内容由工具按需读取，避免小上下文模型被撑爆。
        overview["compact"] = True
        overview["services"] = [{
            "id": s["id"], "name": s["name"], "ports": s["ports"],
            "enabled": s["enabled"], "live_status": s["live_status"],
        } for s in overview["services"]]
        overview["projects"] = [{
            "id": p["id"], "name": p["name"], "root_path": p["root_path"],
        } for p in overview["projects"]]
        overview["commands"] = {
            "count": overview["counts"]["commands"],
            "categories": [c.get("name") for c in (overview["commands"] or {}).get("categories", [])][:12],
        }
        overview["favorite_terminals"] = [{
            "id": t["id"], "name": t["name"], "path": t["path"],
        } for t in overview["favorite_terminals"]]
        overview["ssh_hosts"] = [{
            "id": h["id"], "name": h["name"], "host": h["host"],
            "port": h["port"], "username": h["username"],
        } for h in overview["ssh_hosts"]]
        if docker:
            overview["docker"] = {
                "available": docker.get("available"),
                "containers": [{
                    "id": c.get("id"), "name": c.get("name"),
                    "state": c.get("state"), "status": c.get("status"),
                } for c in (docker.get("containers") or [])[:20]],
                "compose": [{
                    "name": c.get("name"), "path": c.get("path"), "exists": c.get("exists"),
                } for c in (docker.get("compose") or [])[:20]],
            }
        overview["log_sources"] = {
            "count": len(overview["log_sources"]),
            "sample": overview["log_sources"][:5],
        }
        overview["recent_history"] = overview["recent_history"][:3]

    return redact_obj(overview)


async def catalog_detail(item_type: str, item_id: str) -> dict:
    item_type = (item_type or "").strip()
    if item_type == "service":
        return await service_detail(int(item_id))
    if item_type == "project":
        for p in await projects():
            if str(p["id"]) == str(item_id):
                return p
        raise KeyError(f"项目不存在：{item_id}")
    if item_type in ("favorite_terminal", "terminal"):
        for t in await favorite_terminals():
            if str(t["id"]) == str(item_id):
                return t
        raise KeyError(f"常用终端不存在：{item_id}")
    if item_type in ("ssh_host", "ssh"):
        for h in await ssh_hosts():
            if str(h["id"]) == str(item_id):
                return h
        raise KeyError(f"SSH 主机不存在：{item_id}")
    if item_type == "docker_container":
        return await docker_detail(item_id)
    if item_type == "docker_compose":
        info = await docker_info()
        for c in info.get("compose") or []:
            if c.get("path") == item_id or c.get("name") == item_id:
                return c
        raise KeyError(f"Compose 项目不存在：{item_id}")
    if item_type == "command":
        async with get_db() as db:
            rows = await db.execute_fetchall("SELECT * FROM commands WHERE id = ?", (int(item_id),))
        if not rows:
            raise KeyError(f"命令不存在：{item_id}")
        r = dict(rows[0])
        return {
            "id": int(r["id"]),
            "category": r["category"] or "",
            "service": r["service"] or "",
            "scenario": r["scenario"] or "",
            "command": redact_text(r["command"] or ""),
            "description": redact_text(r["description"] or ""),
            "params": _loads(r["params_json"], []),
            "examples": _loads(r["examples_json"], []),
            "source": f"commands#{r['id']}",
        }
    if item_type == "log_source":
        for s in await log_sources():
            if s["path"] == item_id:
                return s
        raise KeyError(f"日志源不存在：{item_id}")
    if item_type == "env":
        info = await env_info()
        groups = [info.get("python") or [], info.get("conda") or [], info.get("node") or [],
                  (info.get("uv") or {}).get("venvs_found") or []]
        for group in groups:
            for e in group:
                if isinstance(e, dict) and (e.get("name") == item_id or e.get("path") == item_id):
                    return e
        raise KeyError(f"环境不存在：{item_id}")
    raise KeyError(f"不支持的配置类型：{item_type}")
