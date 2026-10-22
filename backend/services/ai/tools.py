"""AI 工具定义与只读工具执行。

动作工具不在这里执行；它们由 actions.py 生成待确认动作。
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

import config
from services.ai import catalog
from services.ai.actions import is_action_tool
from services.ai.redact import redact_obj


def _fn(name: str, description: str, properties: dict | None = None,
        required: list[str] | None = None) -> dict:
    params: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        params["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": params,
        },
    }


_ACTION_ENUM = ["start", "stop", "restart"]
_COMPOSE_ENUM = ["up", "stop", "restart"]

TOOLS: list[dict] = [
    _fn(
        "catalog_overview",
        "获取系统配置总览：项目、服务、命令数量、常用终端、SSH 主机、Docker、日志源。"
        "默认是精简索引（名称/ID/端口/状态），需要完整字段时用对应 list/detail 工具。",
        {
            "types": {
                "type": "array",
                "items": {"type": "string",
                          "enum": ["projects", "services", "commands", "terminals",
                                   "ssh", "docker", "logs", "history"]},
                "description": "可选的配置类别；不传则返回默认全部。",
            },
            "include_env": {"type": "boolean", "description": "是否包含环境探测（较慢）。"},
            "include_details": {"type": "boolean",
                                "description": "是否返回完整字段；默认 false。"},
        },
    ),
    _fn("project_list", "列出已配置的项目（名称、根目录、环境、日志路径）。"),
    _fn("project_detail", "查看单个项目详情。",
        {"project_id": {"type": "integer", "description": "项目 ID"}}, ["project_id"]),
    _fn("service_list", "列出服务运行管理里配置的服务，含启动步骤、端口和当前状态。"),
    _fn("service_detail", "查看单个服务配置详情和当前运行状态。",
        {"service_id": {"type": "integer", "description": "服务配置 ID"}}, ["service_id"]),
    _fn("service_status", "查询服务当前运行状态；不传 service_id 则返回全部。",
        {"service_id": {"type": "integer", "description": "服务配置 ID，可选"}}),
    _fn("favorite_terminal_list", "列出已配置的常用终端（备注 + 路径）。"),
    _fn("command_search", "搜索命令手册；不传 query 时返回常用/收藏靠前的命令。",
        {"query": {"type": "string", "description": "关键词，可空"},
         "limit": {"type": "integer", "description": "返回条数，默认 10，最大 50"}}),
    _fn("command_history_recent", "查看最近的终端命令历史，用于理解“上次怎么启动的”。",
        {"limit": {"type": "integer", "description": "返回条数，默认 10，最大 20"}}),
    _fn("ssh_host_list", "列出 SSH 主机元数据（地址、端口、用户）；不包含密码。"),
    _fn("docker_list", "列出 Docker 容器和已登记的 Compose 项目及状态。"),
    _fn("docker_detail", "查看单个容器的详情和最近 80 行日志。",
        {"container_id": {"type": "string", "description": "容器 ID 或名称"}}, ["container_id"]),
    _fn("log_source_list", "列出已导入的日志源和备注。"),
    _fn("env_list", "列出探测到的 Python/Conda/Node/CUDA 等环境（可能较慢）。"),
    _fn("system_snapshot", "获取当前 CPU/内存/磁盘/网络/GPU 快照。"),
    _fn("port_list", "列出当前监听端口。",
        {"limit": {"type": "integer", "description": "返回条数，默认 100"}}),
    # ── 动作工具：只生成建议，不执行 ──
    _fn("service_action", "对已有服务配置提议启动/停止/重启；必须由用户确认后才执行。",
        {"service_id": {"type": "integer", "description": "服务配置 ID"},
         "action": {"type": "string", "enum": _ACTION_ENUM}}, ["service_id", "action"]),
    _fn("docker_container_action", "对已有 Docker 容器提议启动/停止/重启；必须由用户确认。",
        {"container_id": {"type": "string", "description": "容器 ID 或名称"},
         "action": {"type": "string", "enum": _ACTION_ENUM}}, ["container_id", "action"]),
    _fn("docker_compose_action", "对已登记 Compose 项目提议 up/stop/restart；必须由用户确认。",
        {"project_path": {"type": "string", "description": "Compose 项目目录"},
         "action": {"type": "string", "enum": _COMPOSE_ENUM}}, ["project_path", "action"]),
    _fn("open_favorite_terminal", "打开已配置的常用终端；必须由用户确认。",
        {"favorite_id": {"type": "integer", "description": "常用终端 ID"}}, ["favorite_id"]),
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
READ_TOOL_NAMES = TOOL_NAMES - {
    "service_action", "docker_container_action", "docker_compose_action", "open_favorite_terminal",
}


class ToolError(Exception):
    pass


def _int_arg(args: dict, key: str, required: bool = True) -> int | None:
    raw = args.get(key)
    if raw in (None, ""):
        if required:
            raise ToolError(f"缺少参数 {key}")
        return None
    try:
        return int(raw)
    except Exception:
        raise ToolError(f"参数 {key} 必须是整数")


def _str_arg(args: dict, key: str, required: bool = True) -> str:
    raw = args.get(key)
    if raw in (None, ""):
        if required:
            raise ToolError(f"缺少参数 {key}")
        return ""
    return str(raw)


def _finalize(payload: dict) -> dict:
    payload = redact_obj(payload)
    text = json.dumps(payload, ensure_ascii=False, default=str)
    size = len(text.encode("utf-8", errors="replace"))
    if size > config.AI_MAX_TOOL_RESULT_BYTES:
        max_chars = max(2000, config.AI_MAX_TOOL_RESULT_BYTES // 4)
        return {
            "ok": True,
            "truncated": True,
            "preview": text[:max_chars],
            "hint": "结果过大已截断。请缩小查询范围或使用更具体的 detail/limit 参数。",
        }
    return payload


async def execute_read_tool(name: str, args: dict | None = None) -> dict:
    args = args or {}
    if name not in READ_TOOL_NAMES:
        return {"ok": False, "error": f"不是只读工具：{name}"}

    try:
        if name == "catalog_overview":
            types = args.get("types")
            if types is not None and not isinstance(types, list):
                raise ToolError("types 必须是数组")
            data = await catalog.catalog_overview(
                types=[str(x) for x in types] if types else None,
                include_env=bool(args.get("include_env")),
                compact=not bool(args.get("include_details")),
            )
            return _finalize({"ok": True, "data": data})

        if name == "project_list":
            return _finalize({"ok": True, "data": await catalog.projects(), "source": "projects"})

        if name == "project_detail":
            pid = _int_arg(args, "project_id")
            for p in await catalog.projects():
                if p["id"] == pid:
                    return _finalize({"ok": True, "data": p, "source": f"projects#{pid}"})
            raise ToolError(f"项目不存在：{pid}")

        if name == "service_list":
            return _finalize({"ok": True, "data": await catalog.service_configs(),
                              "source": "service_configs"})

        if name == "service_detail":
            sid = _int_arg(args, "service_id")
            try:
                data = await catalog.service_detail(sid)
            except KeyError as e:
                raise ToolError(str(e))
            return _finalize({"ok": True, "data": data, "source": f"service_configs#{sid}"})

        if name == "service_status":
            sid = _int_arg(args, "service_id", required=False)
            if sid is None:
                items = await catalog.service_configs(include_status=True)
                data = [{"id": s["id"], "name": s["name"], "live_status": s["live_status"],
                         "ports": s["ports"], "running": s["live_status"] == "running"}
                        for s in items]
                return _finalize({"ok": True, "data": data, "source": "service_status"})
            try:
                data = await catalog.service_detail(sid)
            except KeyError as e:
                raise ToolError(str(e))
            return _finalize({"ok": True, "data": {
                "id": data["id"], "name": data["name"], "live_status": data["live_status"],
                "ports": data["ports"], "pid": data.get("pid"),
            }, "source": f"service_configs#{sid}"})

        if name == "favorite_terminal_list":
            return _finalize({"ok": True, "data": await catalog.favorite_terminals(),
                              "source": "favorite_terminals"})

        if name == "command_search":
            limit = _int_arg(args, "limit", required=False) or 10
            query = _str_arg(args, "query", required=False)
            return _finalize({"ok": True, "data": await catalog.search_commands(query, limit),
                              "source": "commands"})

        if name == "command_history_recent":
            limit = _int_arg(args, "limit", required=False) or 10
            return _finalize({"ok": True, "data": await catalog.recent_history(limit),
                              "source": "terminal_history"})

        if name == "ssh_host_list":
            return _finalize({"ok": True, "data": await catalog.ssh_hosts(),
                              "source": "ssh_hosts"})

        if name == "docker_list":
            return _finalize({"ok": True, "data": await catalog.docker_info(),
                              "source": "docker"})

        if name == "docker_detail":
            cid = _str_arg(args, "container_id")
            try:
                data = await catalog.docker_detail(cid)
            except KeyError as e:
                raise ToolError(str(e))
            return _finalize({"ok": True, "data": data, "source": f"docker:{cid}"})

        if name == "log_source_list":
            return _finalize({"ok": True, "data": await catalog.log_sources(),
                              "source": "log_sources"})

        if name == "env_list":
            return _finalize({"ok": True, "data": await catalog.env_info(),
                              "source": "env"})

        if name == "system_snapshot":
            return _finalize({"ok": True, "data": await catalog.system_snapshot(),
                              "source": "system"})

        if name == "port_list":
            limit = _int_arg(args, "limit", required=False) or 100
            return _finalize({"ok": True, "data": await catalog.listening_ports(limit),
                              "source": "ports"})

        raise ToolError(f"未实现的工具：{name}")
    except ToolError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def parse_tool_args(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


async def timed_read_tool(name: str, args: dict) -> tuple[dict, int]:
    started = time.time()
    result = await execute_read_tool(name, args)
    return result, int((time.time() - started) * 1000)


def action_tool_info(name: str) -> dict | None:
    if not is_action_tool(name):
        return None
    for t in TOOLS:
        if t["function"]["name"] == name:
            return t
    return None
