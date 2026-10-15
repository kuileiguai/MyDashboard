"""M6 日志读取服务"""

import os
import re
import time
import asyncio
from pathlib import Path


# ── 日志库：导入 / 树形组织 ──

LOG_SUFFIXES = (".log", ".txt", ".out", ".err", ".jsonl")
# 压缩过的日志无法直接按行读取，扫描时跳过
ARCHIVE_SUFFIXES = (".gz", ".bz2", ".xz", ".zst", ".zip", ".7z")


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def looks_like_log(p: Path) -> bool:
    """判断文件名是否像日志文件"""
    name = p.name.lower()
    if name.endswith(ARCHIVE_SUFFIXES):
        return False
    if name.endswith(LOG_SUFFIXES):
        return True
    return "log" in name


def scan_log_files(directory: str, max_files: int = 200, max_depth: int = 6) -> list[str]:
    """扫描目录下的日志文件（跳过隐藏目录与软链接）"""
    root = Path(os.path.expanduser(str(directory)))
    if not root.is_dir():
        return []
    found: list[str] = []
    base_depth = str(root).rstrip("/").count("/")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if str(dirpath).rstrip("/").count("/") - base_depth >= max_depth:
            dirnames[:] = []
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            try:
                if p.is_symlink() or not p.is_file():
                    continue
                if looks_like_log(p):
                    found.append(str(p))
                    if len(found) >= max_files:
                        return found
            except OSError:
                continue
    return found


def stat_log_file(path: str) -> dict:
    """文件状态：是否存在 / 大小 / 修改时间"""
    p = Path(os.path.expanduser(str(path)))
    try:
        st = p.stat()
    except OSError:
        return {"exists": False, "size": 0, "size_human": "-", "mtime": 0, "mtime_human": "-"}
    return {
        "exists": True,
        "size": st.st_size,
        "size_human": human_size(st.st_size),
        "mtime": st.st_mtime,
        "mtime_human": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
    }


def _sort_nodes(nodes: list[dict]) -> None:
    nodes.sort(key=lambda n: (n["type"] != "dir", n["name"].lower()))


def build_log_tree(paths: list[str], remarks: dict | None = None) -> tuple[list[dict], list[dict]]:
    """
    把已导入的日志路径组织成目录树
    返回 (树节点列表, 文件节点扁平列表)
    """
    remarks = remarks or {}
    root: dict = {"name": "/", "path": "/", "type": "dir", "children": []}
    index: dict[str, dict] = {"/": root}

    for raw in paths:
        full = os.path.normpath(os.path.expanduser(str(raw)))
        if not full.startswith("/"):
            full = str(Path(full).resolve())
        parts = [x for x in full.split("/") if x]
        if not parts:
            continue
        cur = root
        prefix = ""
        for i, part in enumerate(parts):
            prefix = f"{prefix}/{part}"
            last = i == len(parts) - 1
            node = index.get(prefix)
            if node is None:
                node = {"name": part, "path": prefix, "type": "file" if last else "dir"}
                if not last:
                    node["children"] = []
                index[prefix] = node
                cur.setdefault("children", []).append(node)
            elif node["type"] == "file" and not last:
                node["type"] = "dir"
                node["children"] = []
            if not last:
                cur = node

    files: list[dict] = []

    def decorate(node: dict) -> None:
        node["remark"] = remarks.get(node["path"], "")
        if node["type"] == "file":
            node.update(stat_log_file(node["path"]))
            files.append(node)
            return
        total = count = missing = 0
        for child in node.get("children", []):
            decorate(child)
            if child["type"] == "file":
                count += 1
                total += child.get("size", 0)
                missing += 0 if child.get("exists") else 1
            else:
                count += child.get("file_count", 0)
                total += child.get("total_size", 0)
                missing += child.get("missing_count", 0)
        node["file_count"] = count
        node["total_size"] = total
        node["size_human"] = human_size(total)
        node["missing_count"] = missing
        try:
            node["exists"] = os.path.isdir(node["path"])
        except OSError:
            node["exists"] = False

    for child in root.get("children", []):
        decorate(child)
    _sort_nodes(root["children"])
    return root["children"], files


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
