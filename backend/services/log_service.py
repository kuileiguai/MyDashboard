"""M6 日志读取服务"""

import os
import re
import asyncio
from pathlib import Path


async def read_log(path: str, offset: int = 0, limit: int = 100) -> dict:
    """分页读取日志文件"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": "File not found", "lines": [], "size": 0}
    
    size = p.stat().st_size
    
    # Stream read: seek to offset, align to line boundary
    lines = []
    with open(p, "rb") as f:
        f.seek(offset)
        if offset > 0:
            # Skip partial line
            f.readline()
        
        for _ in range(limit):
            line = f.readline()
            if not line:
                break
            try:
                decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
            except Exception:
                decoded = line.decode("latin-1", errors="replace").rstrip("\n\r")
            lines.append({
                "offset": f.tell() - len(line),
                "text": decoded,
                "level": _detect_level(decoded),
            })
    
    return {
        "lines": lines,
        "size": size,
        "next_offset": offset + sum(len(l["text"].encode("utf-8", errors="replace")) + 1 for l in lines),
        "has_more": offset + sum(len(l["text"].encode("utf-8", errors="replace")) + 1 for l in lines) < size,
    }


def _detect_level(line: str) -> str:
    up = line.upper()
    if "ERROR" in up or "FATAL" in up or "CRIT" in up or "EXCEPTION" in up or "TRACEBACK" in up:
        return "error"
    if "WARN" in up or "WARNING" in up:
        return "warn"
    if "INFO" in up:
        return "info"
    if "DEBUG" in up:
        return "debug"
    return ""


async def search_log(path: str, pattern: str, limit: int = 200) -> dict:
    """正则搜索日志文件"""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"error": "File not found", "matches": []}
    
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return {"error": f"Invalid regex: {e}", "matches": []}
    
    matches = []
    with open(p, "rb") as f:
        for line_num, line in enumerate(f, 1):
            if len(matches) >= limit:
                break
            try:
                decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
            except Exception:
                decoded = line.decode("latin-1", errors="replace").rstrip("\n\r")
            if regex.search(decoded):
                matches.append({
                    "line_num": line_num,
                    "text": decoded,
                    "level": _detect_level(decoded),
                })
    
    return {"matches": matches, "total_matches": len(matches)}
