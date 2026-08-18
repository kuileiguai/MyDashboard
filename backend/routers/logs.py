"""M6 日志查看器 路由"""

import os, asyncio
from pathlib import Path
from fastapi import APIRouter, Query, HTTPException
from services.log_service import read_log, search_log
from database import get_db

router = APIRouter()


@router.get("")
async def get_log(path: str, offset: int = 0, limit: int = 100):
    return await read_log(path, offset, limit)


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
