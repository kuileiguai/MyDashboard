"""终端输出记录服务（文本镜像的数据源）

已存在的终端输出流无法事后读取（pty 的消费者唯一），所以文本镜像走"事前记录"：
shell 启动时套一层 `script -q -f`，该终端看到的全部输出实时落盘；
面板读日志并交给 xterm.js 渲染 —— 得到的是**真正的文本**（可复制、可回滚），而不是截图。

日志文件： ~/.deckpit/logs/term-<时间戳>-<pid>.log
元信息：   ~/.deckpit/logs/term-<时间戳>-<pid>.meta.json

日志含 ANSI 转义序列，xterm.js 直接 write 即可还原终端外观。
"""

import json
import os
import re
from pathlib import Path

LOG_DIR = Path.home() / ".deckpit" / "logs"

# 首次打开时最多回放的字节数，避免超大日志把浏览器卡住
MAX_INITIAL_BYTES = 2 * 1024 * 1024

# 文件名白名单：只允许 term-xxx.log 这类，阻断目录穿越
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def log_dir() -> Path:
    return LOG_DIR


def _safe_path(name: str) -> Path | None:
    """把前端传来的文件名限制在 logs 目录内"""
    if not name or not _SAFE_NAME.match(name):
        return None
    if ".." in name:
        return None
    p = (LOG_DIR / name).resolve()
    try:
        if p.parent != LOG_DIR.resolve():
            return None
    except OSError:
        return None
    return p


def _meta_path(name: str) -> Path | None:
    """term-20261014-172000-1234.log -> term-20261014-172000-1234.meta.json"""
    if not name.endswith(".log"):
        return None
    return _safe_path(name[:-4] + ".meta.json")


def _read_meta(name: str) -> dict:
    p = _meta_path(name)
    if not p or not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _alive(meta: dict) -> bool:
    pid = meta.get("pid")
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    return pid > 0 and os.path.exists(f"/proc/{pid}")


def list_sessions() -> list[dict]:
    """列出所有已记录的终端会话（新的在前）"""
    if not LOG_DIR.is_dir():
        return []
    sessions = []
    for log in LOG_DIR.glob("*.log"):
        try:
            st = log.stat()
        except OSError:
            continue
        meta = _read_meta(log.name)
        sessions.append({
            "name": log.name,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "pid": meta.get("pid"),
            "cwd": meta.get("cwd") or "",
            "started": meta.get("started") or "",
            "shell": meta.get("shell") or "",
            "alive": _alive(meta),
        })
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def sessions_by_pid() -> dict[int, str]:
    """PID -> 日志文件名，用于把外部终端窗口关联到它的日志"""
    return {
        int(s["pid"]): s["name"]
        for s in list_sessions()
        if s["pid"] and str(s["pid"]).isdigit()
    }


def read_log(name: str, offset: int = 0) -> dict | None:
    """增量读取日志文本。

    offset=0 且日志很大时只回放最后 MAX_INITIAL_BYTES 字节（并给出真实起始位置）。
    返回 {"data", "offset", "size", "truncated", "alive"}。
    """
    p = _safe_path(name)
    if not p or not p.is_file():
        return None

    size = p.stat().st_size
    start = max(0, min(int(offset or 0), size))
    if offset == 0 and size > MAX_INITIAL_BYTES:
        start = size - MAX_INITIAL_BYTES

    try:
        with open(p, "rb") as f:
            f.seek(start)
            raw = f.read()
    except OSError:
        return None

    text = raw.decode("utf-8", errors="replace")
    # 截断回放时可能从转义序列中间断开，补一个重置序列避免首屏乱码
    if start > 0:
        text = "\x1b[0m" + text.split("\n", 1)[-1] if "\n" in text else text

    return {
        "data": text,
        "offset": start,
        "size": size,
        "truncated": start > 0,
        "alive": _alive(_read_meta(name)),
    }


def delete_log(name: str) -> bool:
    """删除一个已结束会话的日志及其元信息"""
    p = _safe_path(name)
    meta = _meta_path(name)
    if not p or not p.is_file():
        return False
    try:
        p.unlink()
        if meta and meta.is_file():
            meta.unlink()
        return True
    except OSError:
        return False
