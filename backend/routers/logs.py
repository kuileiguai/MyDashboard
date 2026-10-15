"""M6 日志查看器 路由"""

import os, asyncio, json
from pathlib import Path
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from services.log_service import (
    read_log, search_log, scan_log_files, build_log_tree, looks_like_log, human_size,
)
from database import get_db

router = APIRouter()


@router.get("")
async def get_log(path: str, offset: int = 0, limit: int = 100):
    return await read_log(path, offset, limit)


@router.get("/browse")
async def browse_dir(path: str = "~", logs_only: bool = True):
    """
    浏览目录，供导入时以文件夹树选择文件/文件夹
    logs_only=true 时只列出像日志的文件（目录始终列出）
    """
    p = Path(os.path.expanduser(str(path or "~")))
    try:
        resolved = p.resolve()
        if not resolved.is_dir():
            return {"current": str(p), "parent": "", "items": [], "error": "不是目录"}
        entries = sorted(resolved.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return {"current": str(p), "parent": "", "items": [], "error": "无权限访问该目录"}
    except OSError as e:
        return {"current": str(p), "parent": "", "items": [], "error": str(e)}

    items = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir:
            items.append({"name": entry.name, "path": str(entry), "is_dir": True})
            continue
        if logs_only and not looks_like_log(entry):
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        items.append({"name": entry.name, "path": str(entry), "is_dir": False,
                      "size": size, "size_human": human_size(size)})
    return {"current": str(resolved), "parent": str(resolved.parent), "items": items}


# ── 日志库：导入的日志文件（树形）+ 备注 ──

_LIB_KEY = "log_files"
_REMARK_KEY = "log_remarks"


async def _load_library() -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = ?", (_LIB_KEY,))
    if not rows:
        return []
    try:
        data = json.loads(rows[0]["value"])
    except Exception:
        return []
    return [x for x in data if isinstance(x, dict) and x.get("path")] if isinstance(data, list) else []


async def _save_library(entries: list[dict]) -> None:
    async with get_db() as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                         (_LIB_KEY, json.dumps(entries, ensure_ascii=False)))
        await db.commit()


async def _load_remarks() -> dict:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = ?", (_REMARK_KEY,))
    if not rows:
        return {}
    try:
        data = json.loads(rows[0]["value"])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _save_remarks(remarks: dict) -> None:
    async with get_db() as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                         (_REMARK_KEY, json.dumps(remarks, ensure_ascii=False)))
        await db.commit()


@router.get("/library")
async def get_library():
    """已导入的日志文件（树形 + 扁平列表），并复核文件是否还在"""
    entries = await _load_library()
    remarks = await _load_remarks()
    paths = [e["path"] for e in entries]
    tree, files = build_log_tree(paths, remarks)
    return {"tree": tree, "files": files, "remarks": remarks, "count": len(files)}


class LibraryImport(BaseModel):
    paths: list[str]


@router.post("/library")
async def import_library(body: LibraryImport):
    """导入日志文件；目录会递归扫描其中的日志文件"""
    from datetime import datetime
    entries = await _load_library()
    known = {e["path"] for e in entries}
    added, errors = [], []
    for raw in body.paths:
        raw = (raw or "").strip()
        if not raw:
            continue
        p = Path(os.path.expanduser(raw))
        if p.is_dir():
            candidates = scan_log_files(str(p))
            if not candidates:
                errors.append(f"{raw}：目录中没有发现日志文件")
            for c in candidates:
                if c not in known:
                    known.add(c)
                    added.append(c)
        elif p.is_file():
            target = str(p.resolve()) if str(p).startswith("/") else str(p)
            if target in known:
                continue
            known.add(target)
            added.append(target)
        else:
            errors.append(f"{raw}：路径不存在")

    now = datetime.now().isoformat(timespec="seconds")
    entries.extend({"path": p, "added_at": now} for p in added)
    await _save_library(entries)
    return {"ok": True, "added": len(added), "total": len(entries), "paths": added, "errors": errors}


class LibraryRemove(BaseModel):
    path: str


@router.delete("/library")
async def remove_library(body: LibraryRemove):
    entries = await _load_library()
    remaining = [e for e in entries if e["path"] != body.path]
    await _save_library(remaining)
    remarks = await _load_remarks()
    if body.path in remarks:
        remarks.pop(body.path)
        await _save_remarks(remarks)
    return {"ok": True, "removed": len(entries) - len(remaining)}


class LogRemark(BaseModel):
    path: str
    remark: str


@router.get("/remarks")
async def get_remarks():
    return await _load_remarks()


@router.post("/remarks")
async def save_remark(body: LogRemark):
    """给日志文件或日志文件夹写备注（留空即清除）"""
    remarks = await _load_remarks()
    if body.remark.strip():
        remarks[body.path] = body.remark.strip()
    else:
        remarks.pop(body.path, None)
    await _save_remarks(remarks)
    return {"ok": True, "remarks": remarks}


@router.get("/search")
async def search_logs(path: str, pattern: str = "", limit: int = 200):
    return await search_log(path, pattern, limit)


# ── M6-F8: 多日志聚合视图 ──

@router.get("/aggregate")
async def aggregate_logs(paths: str = Query(...), keywords: str = Query(""), limit: int = Query(500)):
    """
    多日志源按时间交错聚合显示
    paths: 逗号分隔的日志文件路径列表
    keywords: 可选过滤关键词（逗号分隔）
    """
    file_paths = [p.strip() for p in paths.split(",") if p.strip()]
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    all_lines = []

    for fp in file_paths:
        p = Path(fp).expanduser().resolve()
        if not p.exists():
            continue
        try:
            result = await read_log(fp, 0, 500)
            for line in result.get("lines", []):
                # Skip if keyword filter active
                if keyword_list and not any(
                    kw.lower() in line["text"].lower() for kw in keyword_list
                ):
                    continue
                all_lines.append({
                    "source": fp.split("/")[-1],
                    "source_path": fp,
                    "text": line["text"],
                    "level": line.get("level", ""),
                    "offset": line.get("offset", 0),
                    "ts": _try_parse_timestamp(line["text"]),
                })
        except Exception:
            pass

    # Simple time-interleave: group by source
    return {"lines": all_lines, "total": len(all_lines),
            "sources": list(set(l["source"] for l in all_lines))}


def _try_parse_timestamp(text: str) -> float:
    """尝试从日志行提取时间戳，用于 M6-F9 时间线对齐"""
    import re
    from datetime import datetime
    # Common timestamp patterns
    patterns = [
        (r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", "%Y-%m-%dT%H:%M:%S"),
        (r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", "%Y-%m-%d %H:%M:%S"),
        (r"(\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2})", "%d/%b/%Y:%H:%M:%S"),
        (r"(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})", "%b %d %H:%M:%S"),
    ]
    for pattern, fmt in patterns:
        m = re.search(pattern, text)
        if m:
            try:
                dt = datetime.strptime(m.group(1), fmt)
                return dt.timestamp()
            except ValueError:
                continue
    return 0


# ── M6-F9: 时间线对齐 ──

@router.get("/timeline")
async def timeline_align(paths: str = Query(...), limit: int = Query(500)):
    """
    多日志按时间戳对齐对照
    """
    file_paths = [p.strip() for p in paths.split(",") if p.strip()]
    all_lines = []
    for fp in file_paths:
        p = Path(fp).expanduser().resolve()
        if not p.exists():
            continue
        try:
            result = await read_log(fp, 0, limit)
            for line in result.get("lines", []):
                ts = _try_parse_timestamp(line["text"])
                all_lines.append({
                    "source": fp.split("/")[-1],
                    "source_path": fp,
                    "text": line["text"],
                    "level": line.get("level", ""),
                    "ts": ts,
                })
        except Exception:
            pass

    # Sort by timestamp
    all_lines.sort(key=lambda x: x["ts"])
    return {"lines": all_lines, "total": len(all_lines),
            "sources": list(set(l["source"] for l in all_lines))}


# ── M6-F10: ERROR 告警订阅 ──

# 全局告警订阅者集合
_alert_subscribers: list = []


def add_alert_subscriber(q: asyncio.Queue):
    _alert_subscribers.append(q)


def remove_alert_subscriber(q: asyncio.Queue):
    if q in _alert_subscribers:
        _alert_subscribers.remove(q)


async def notify_error_alert(source: str, text: str):
    """通知所有订阅者有新的 ERROR 日志"""
    for q in _alert_subscribers:
        try:
            await q.put({"source": source, "text": text, "type": "error_alert"})
        except Exception:
            pass


@router.get("/alerts/subscribe")
async def subscribe_alerts():
    """返回当前告警订阅状态"""
    return {"subscriber_count": len(_alert_subscribers)}
