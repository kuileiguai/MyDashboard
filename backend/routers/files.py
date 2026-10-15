"""M2 文件管理 路由"""

import os, shutil, json, asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from database import get_db
from config import ALLOWED_ROOTS

router = APIRouter()


class FileOp(BaseModel):
    path: str
    new_path: str = ""
    confirm: bool = False


def _safe_path(user_path: str) -> Path:
    p = Path(user_path).expanduser().resolve()
    for root in ALLOWED_ROOTS:
        try:
            p.relative_to(root)
            return p
        except ValueError:
            continue
    raise HTTPException(403, "Path outside allowed roots")


@router.get("")
async def list_dir(path: str = "~"):
    p = _safe_path(path)
    if not p.exists():
        raise HTTPException(404, "Path not found")
    items = []
    for entry in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        try:
            st = entry.stat()
            items.append({
                "name": entry.name, "path": str(entry), "is_dir": entry.is_dir(),
                "size": st.st_size if not entry.is_dir() else 0, "mtime": st.st_mtime,
            })
        except PermissionError:
            items.append({"name": entry.name, "path": str(entry), "is_dir": entry.is_dir(),
                          "size": 0, "mtime": 0, "error": "Permission denied"})
    parts = []
    for par in p.parents:
        parts.append({"name": par.name or "/", "path": str(par)})
    parts.reverse()
    parts.append({"name": p.name or "/", "path": str(p)})
    return {"current": str(p), "breadcrumbs": parts, "items": items}


@router.post("/mkdir")
async def mkdir(body: FileOp):
    _safe_path(body.path).mkdir(parents=True, exist_ok=True)
    return {"ok": True}


@router.post("/touch")
async def touch(body: FileOp):
    _safe_path(body.path).touch(exist_ok=True)
    return {"ok": True}


@router.post("/rename")
async def rename(body: FileOp):
    _safe_path(body.path).rename(_safe_path(body.new_path))
    return {"ok": True}


@router.post("/copy")
async def copy(body: FileOp):
    src = _safe_path(body.path)
    dst = _safe_path(body.new_path)
    if src.is_dir(): shutil.copytree(str(src), str(dst))
    else: shutil.copy2(str(src), str(dst))
    return {"ok": True}


@router.post("/move")
async def move(body: FileOp):
    shutil.move(str(_safe_path(body.path)), str(_safe_path(body.new_path)))
    return {"ok": True}


@router.delete("")
async def delete(body: FileOp):
    if not body.confirm: raise HTTPException(400, "confirm required")
    p = _safe_path(body.path)
    if p.is_dir(): shutil.rmtree(str(p))
    else: p.unlink()
    return {"ok": True}


@router.get("/bookmarks")
async def list_bookmarks():
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM bookmarks ORDER BY sort_order")
    return [dict(r) for r in rows]


@router.post("/bookmarks")
async def create_bookmark(name: str = Query(...), path: str = Query(...)):
    async with get_db() as db:
        cur = await db.execute("INSERT INTO bookmarks (name, path) VALUES (?,?)", (name, path))
        await db.commit()
        return {"id": cur.lastrowid}


@router.delete("/bookmarks/{bm_id}")
async def delete_bookmark(bm_id: int):
    async with get_db() as db:
        await db.execute("DELETE FROM bookmarks WHERE id = ?", (bm_id,))
        await db.commit()
    return {"ok": True}


# ── M2-F9: 最近打开文件 ──

@router.get("/recent")
async def recent_files(limit: int = 20):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM recent_files ORDER BY opened_at DESC LIMIT ?", (limit,)
        )
    return [dict(r) for r in rows]


@router.post("/recent")
async def record_recent(path: str = Query(...)):
    async with get_db() as db:
        await db.execute("DELETE FROM recent_files WHERE path = ?", (path,))
        await db.execute("INSERT INTO recent_files (path) VALUES (?)", (path,))
        await db.commit()
    return {"ok": True}


# ── M2-F8: 文件模板库 ──

@router.get("/templates")
async def list_templates():
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT * FROM file_templates ORDER BY id")
    return [dict(r) for r in rows]


@router.post("/templates")
async def create_template(name: str = Query(...), extension: str = Query(...), content: str = Query("")):
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO file_templates (name, extension, content) VALUES (?,?,?)",
            (name, extension, content),
        )
        await db.commit()
        return {"id": cur.lastrowid}


@router.delete("/templates/{tid}")
async def delete_template(tid: int):
    async with get_db() as db:
        await db.execute("DELETE FROM file_templates WHERE id = ?", (tid,))
        await db.commit()
    return {"ok": True}


# ── M2-F10: 外部 Nautilus 窗口检测 ──

@router.get("/nautilus-windows")
async def list_nautilus_windows():
    """检测桌面上已打开的 Nautilus 窗口"""
    windows = []
    try:
        import subprocess
        # 用 -x 获取窗口类名，Nautilus 的类是 org.gnome.Nautilus
        proc = subprocess.run(
            ["wmctrl", "-l", "-x"],
            capture_output=True, text=True, timeout=3
        )
        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(None, 4)  # id, desktop, class, host, title
            if len(parts) < 5:
                continue
            win_id, desktop, win_class, host, title = parts
            # 检查窗口类名是否包含 Nautilus
            if "nautilus" not in win_class.lower() and "nautilus" not in title.lower():
                continue

            windows.append({
                "id": win_id,
                "desktop": int(desktop) if desktop.lstrip('-').isdigit() else -1,
                "host": host,
                "title": title,
                "class": win_class,
                "path": _extract_nautilus_path_by_pid(win_id),
            })
    except Exception:
        pass
    return windows


def _extract_nautilus_path_by_pid(win_id: str) -> str:
    """通过窗口标题（文件夹basename）搜索完整路径"""
    import subprocess, os

    # 1. 获取窗口标题
    title = ""
    try:
        proc = subprocess.run(
            ["xdotool", "getwindowname", win_id],
            capture_output=True, text=True, timeout=2
        )
        title = proc.stdout.strip()
    except Exception:
        return ""

    if not title or title in ("主文件夹", "Home"):
        return os.path.expanduser("~")

    # 2. 在常用位置搜索该文件夹名（找到第一个即退出）
    search_roots = [r for r in [os.path.expanduser("~"), "/mnt", "/opt"] if os.path.isdir(r)]
    try:
        find_args = (["find"] + search_roots +
                     ["-maxdepth", "5", "-type", "d", "-name", title,
                      "-printf", "%p\n", "-quit"])
        proc = subprocess.run(find_args, capture_output=True, text=True, timeout=4)
        found = proc.stdout.strip()
        if found:
            return found
    except Exception:
        pass

    return ""


@router.post("/nautilus-windows/{win_id}/focus")
async def focus_nautilus(win_id: str):
    import subprocess
    try:
        subprocess.run(["wmctrl", "-i", "-a", win_id], timeout=3)
        return {"ok": True}
    except Exception:
        return {"ok": False, "error": "wmctrl not available"}


@router.post("/nautilus-windows/{win_id}/close")
async def close_nautilus(win_id: str):
    import subprocess
    try:
        subprocess.run(["wmctrl", "-i", "-c", win_id], timeout=3)
        return {"ok": True}
    except Exception:
        return {"ok": False, "error": "wmctrl not available"}


# ── Nautilus 窗口别名（备注名）──

@router.get("/nautilus-aliases")
async def get_nautilus_aliases():
    """获取 Nautilus 窗口别名映射 {win_id: alias}"""
    import json
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'nautilus_aliases'")
    if row:
        try:
            return json.loads(row[0]["value"])
        except Exception:
            pass
    return {}


class NautilusAlias(BaseModel):
    win_id: str
    alias: str


@router.post("/nautilus-aliases")
async def save_nautilus_alias(body: NautilusAlias):
    """保存单个 Nautilus 窗口别名（alias 为空则清除）"""
    import json
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'nautilus_aliases'")
        aliases = json.loads(row[0]["value"]) if row else {}
        if body.alias.strip():
            aliases[body.win_id] = body.alias.strip()
        else:
            aliases.pop(body.win_id, None)
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('nautilus_aliases', ?)",
            (json.dumps(aliases),),
        )
        await db.commit()
    return {"ok": True, "aliases": aliases}


# ── 磁盘占用方块图（SpaceSniffer 式下钻）──

# 简单 LRU：同一路径 30 秒内复用上次扫描结果，避免来回下钻反复跑 du
_DISK_USAGE_CACHE: dict[str, tuple[float, dict]] = {}
_DISK_USAGE_TTL = 30.0
_DISK_USAGE_MAX = 64
# 单次扫描内部信号：用于客户端断连/取消时终止后台 du 子进程
_SCAN_CANCEL: dict[str, asyncio.Event] = {}

# ── 已知伪文件系统（vfs）路径 ──
# 这些路径下的文件 stat() 会返回"假大小"（如 /proc/<pid>/mem = 128TB），
# 不递归 du 它们，避免结果虚高。
_VFS_DIR_NAMES: frozenset[str] = frozenset({
    "proc", "sys", "dev", "run", "snap",
    ".snapshots",  # btrfs snap 通常不计入用户数据
})
_VFS_PATH_EXACT: frozenset[str] = frozenset({
    "/proc", "/sys", "/dev", "/run", "/snap", "/boot/efi", "/lost+found",
})


def _is_vfs_path(path: str) -> bool:
    """判断路径是否位于伪文件系统下（du 不应递归这些）"""
    p = path.rstrip("/")
    if p in _VFS_PATH_EXACT:
        return True
    # /proc/<pid>/mem 这类用 basename 判断更稳
    parts = p.split("/")
    if any(part in _VFS_DIR_NAMES for part in parts if part):
        return True
    return False


def _disk_usage_cached_get(path_key: str) -> dict | None:
    entry = _DISK_USAGE_CACHE.get(path_key)
    if not entry:
        return None
    ts, payload = entry
    if (asyncio.get_event_loop().time() - ts) > _DISK_USAGE_TTL:
        _DISK_USAGE_CACHE.pop(path_key, None)
        return None
    return payload


def _disk_usage_cached_put(path_key: str, payload: dict) -> None:
    if len(_DISK_USAGE_CACHE) >= _DISK_USAGE_MAX:
        # 简单 FIFO 淘汰
        oldest = next(iter(_DISK_USAGE_CACHE))
        _DISK_USAGE_CACHE.pop(oldest, None)
    _DISK_USAGE_CACHE[path_key] = (asyncio.get_event_loop().time(), payload)


def _scandir_one_level(p: Path) -> list[dict]:
    """毫秒级：只 scandir 一级，不递归。

    文件 size = stat().st_size（直接拿）
    目录 size = 0（待后续并发 du 补全；扫描期间前端会显示 "计算中..."）
    vfs 目录 size = 0 且不并发 du（避免 /proc/<pid>/mem 这种 128TB 假大小）
    """
    out: list[dict] = []
    try:
        with os.scandir(str(p)) as it:
            for entry in it:
                full_path = str(Path(p) / entry.name)
                # 跳过 vfs 子目录（如 /proc/<pid>、/sys/devices/...）
                if _is_vfs_path(full_path):
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                    is_dir = entry.is_dir(follow_symlinks=False)
                    out.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else st.st_size,
                        "st_dev": st.st_dev,
                        "pending": is_dir,  # 标记目录待并发 du
                    })
                except OSError:
                    # 单项失败跳过（无权限、文件消失等）
                    continue
    except OSError as e:
        raise HTTPException(403, f"Cannot read directory: {e}")
    return out


async def _du_one(path: str, timeout: float, cancel: asyncio.Event) -> tuple[int, bool]:
    """异步 `du -sbx path`，返回 (字节数, 是否超时/失败)。

    -sbx: bytes / apparent size / stay on single filesystem / summary
    对单个目录递归算自身占用，比 `du --max-depth=1` 跑整个子树快得多。

    防御性：vfs 路径直接返回 0，不调用 du。
    """
    if cancel.is_set():
        return 0, True
    if _is_vfs_path(path):
        return 0, False
    proc = await asyncio.create_subprocess_exec(
        "du", "-sbx",
        # 防御性：万一 scandir 没过滤掉，再用 du 自身的 exclude 双保险
        # GNU du 的 --exclude 匹配 basename 并递归跳过该目录
        "--exclude=proc", "--exclude=sys", "--exclude=dev",
        "--exclude=run", "--exclude=snap",
        path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
        return 0, True
    if cancel.is_set():
        return 0, True
    line = stdout.decode().strip().split("\t")
    if len(line) >= 2:
        try:
            return int(line[0]), False
        except ValueError:
            return 0, True
    return 0, True


async def _parallel_du_dirs(
    entries: list[dict],
    timeout: float,
    max_concurrent: int,
    cancel: asyncio.Event,
    on_done=None,
) -> int:
    """并发 du entries 中所有 is_dir 目录（每个 du 独立递归各自的子树）。

    这是关键性能优化：
      单线程 `du --max-depth=1 /home` 是递归整个 /home 后只输出顶层；
      并发 `du -sbx /home/user1 /home/user2 ...` 把 IO 分散到多个进程，
      突破单线程机械盘 IO 瓶颈。

    on_done: 每完成一个 du 时回调（用于流式推送增量结果到前端）。
    返回超时/失败的目录数。
    """
    sem = asyncio.Semaphore(max_concurrent)
    timeout_count = 0

    async def run(entry: dict) -> None:
        nonlocal timeout_count
        if not entry.get("is_dir") or cancel.is_set():
            entry["pending"] = False
            return
        # 防御性：vfs 路径直接标记为 0，不递归
        if _is_vfs_path(entry["path"]):
            entry["size"] = 0
            entry["pending"] = False
            entry["is_vfs"] = True
            return
        async with sem:
            size, failed = await _du_one(entry["path"], timeout, cancel)
            entry["size"] = size
            entry["size_timeout"] = failed
            entry["pending"] = False
            if failed:
                timeout_count += 1
            if on_done is not None:
                try:
                    on_done(entry)
                except Exception:
                    pass

    await asyncio.gather(*[run(e) for e in entries if e.get("is_dir")])
    return timeout_count


@router.get("/disk-usage")
async def disk_usage(
    path: str = Query("~"),
    limit: int = Query(80, ge=1, le=500),
    timeout: float = Query(15.0, ge=1.0, le=60.0),
    concurrent: int = Query(8, ge=1, le=32),
    stream: bool = Query(False, description="True 时返回 NDJSON 流（渐进推送）"),
):
    """扫描目录一级子项（仿 ncdu / Baobab）。

    默认非流式：scandir 一级（毫秒级）+ 并发 du 每个子目录（IO 并行）。
    stream=true：返回 NDJSON 流，初始事件携带一级列表，后续事件每完成
                 一个子目录 du 就推送一条，客户端可实时刷新 treemap。

    返回字段（items 元素）：
      name, path, is_dir, size (bytes), pending, size_timeout
    """
    import time

    p = _safe_path(path)
    if not p.is_dir():
        raise HTTPException(400, "Path is not a directory")

    cache_key = str(p)
    cached = _disk_usage_cached_get(cache_key)
    if cached is not None:
        items_all: list[dict] = cached["_items_all"]
        sliced = [
            {
                "name": e["name"],
                "path": e["path"],
                "is_dir": e["is_dir"],
                "size": e["size"],
                "is_vfs": e.get("is_vfs", False),
                "size_timeout": e.get("size_timeout", False),
            }
            for e in items_all[:limit]
        ]
        if not stream:
            return {
                "path": cached["path"],
                "items": sliced,
                "others_size": sum(x["size"] for x in items_all[limit:]),
                "truncated": cached["truncated"],
                "elapsed_ms": cached["elapsed_ms"],
                "stats": cached["stats"],
                "cached": True,
            }
        # 流式：直接吐一份初始 + 完成事件
        async def gen_cached():
            yield _ndjson({
                "phase": "initial",
                "path": cached["path"],
                "items": sliced,
                "others_size": sum(x["size"] for x in items_all[limit:]),
                "stats": cached["stats"],
                "cached": True,
            })
            yield _ndjson({"phase": "done", "cached": True})
        return StreamingResponse(gen_cached(), media_type="application/x-ndjson")

    t0 = time.monotonic()
    entries = _scandir_one_level(p)
    scandir_ms = int((time.monotonic() - t0) * 1000)

    if not stream:
        # 非流式：等所有 du 完成再一次性返回
        cancel = asyncio.Event()
        _SCAN_CANCEL[cache_key] = cancel
        try:
            timeout_count = await _parallel_du_dirs(
                entries, timeout=timeout, max_concurrent=concurrent, cancel=cancel,
            )
        finally:
            _SCAN_CANCEL.pop(cache_key, None)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        entries.sort(key=lambda x: x["size"], reverse=True)
        sliced = [
            {
                "name": e["name"],
                "path": e["path"],
                "is_dir": e["is_dir"],
                "size": e["size"],
                "is_vfs": e.get("is_vfs", False),
                "size_timeout": e.get("size_timeout", False),
            }
            for e in entries[:limit]
        ]
        others_size = sum(e["size"] for e in entries[limit:])
        stats = {
            "total": len(entries),
            "dirs": sum(1 for e in entries if e["is_dir"]),
            "files": sum(1 for e in entries if not e["is_dir"]),
            "timeouts": timeout_count,
            "scandir_ms": scandir_ms,
        }

        payload = {
            "path": str(p),
            "items": sliced,
            "others_size": others_size,
            "truncated": timeout_count > 0,
            "elapsed_ms": elapsed_ms,
            "stats": stats,
            "_items_all": entries,
        }
        _disk_usage_cached_put(cache_key, payload)

        return {
            "path": payload["path"],
            "items": payload["items"],
            "others_size": payload["others_size"],
            "truncated": payload["truncated"],
            "elapsed_ms": payload["elapsed_ms"],
            "stats": payload["stats"],
            "cached": False,
        }

    # 流式：NDJSON，每行一条事件
    cancel = asyncio.Event()
    _SCAN_CANCEL[cache_key] = cancel

    # 队列：du worker 完成一个 entry 就放进来，async generator 从队列取
    queue: asyncio.Queue = asyncio.Queue()

    def on_done(entry: dict) -> None:
        # 把已完成的 entry 投到队列
        queue.put_nowait({
            "phase": "update",
            "item": {
                "name": entry["name"],
                "path": entry["path"],
                "is_dir": entry["is_dir"],
                "size": entry["size"],
                "size_timeout": entry.get("size_timeout", False),
            },
        })

    async def producer():
        """后台：并发 du，每完成一个就 on_done；最后发 done 事件。"""
        timeout_count = 0
        try:
            timeout_count = await _parallel_du_dirs(
                entries, timeout=timeout, max_concurrent=concurrent,
                cancel=cancel, on_done=on_done,
            )
        except asyncio.CancelledError:
            pass
        finally:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            queue.put_nowait({
                "phase": "done",
                "truncated": timeout_count > 0,
                "elapsed_ms": elapsed_ms,
                "stats": {
                    "total": len(entries),
                    "dirs": sum(1 for e in entries if e["is_dir"]),
                    "files": sum(1 for e in entries if not e["is_dir"]),
                    "timeouts": timeout_count,
                    "scandir_ms": scandir_ms,
                },
            })

    async def gen():
        # 1) 立刻发 initial（scandir 一级已完成，目录 size=0 / pending=True）
        initial_items = [
            {
                "name": e["name"],
                "path": e["path"],
                "is_dir": e["is_dir"],
                "size": e["size"],  # 文件是真实大小，目录是 0
                "pending": e["is_dir"] and not e.get("is_vfs", False),
                "is_vfs": e.get("is_vfs", False),
            }
            for e in entries
        ]
        # 按 size 预排序：文件优先（大文件靠前），目录集中到后
        initial_items.sort(key=lambda x: (x["is_dir"], -x["size"]))
        sliced = initial_items[:limit]
        others_size = sum(x["size"] for x in initial_items[limit:])
        yield _ndjson({
            "phase": "initial",
            "path": str(p),
            "items": sliced,
            "others_size": others_size,
            "stats": {
                "total": len(initial_items),
                "dirs": sum(1 for x in initial_items if x["is_dir"]),
                "files": sum(1 for x in initial_items if not x["is_dir"]),
                "scandir_ms": scandir_ms,
            },
            "cached": False,
        })

        # 2) 启动后台 producer
        prod_task = asyncio.create_task(producer())

        # 3) 持续从队列读 update / done
        try:
            while True:
                msg = await queue.get()
                yield _ndjson(msg)
                if msg.get("phase") == "done":
                    break
        finally:
            cancel.set()  # 通知 worker 终止
            try:
                await asyncio.wait_for(prod_task, timeout=2.0)
            except asyncio.TimeoutError:
                prod_task.cancel()
            _SCAN_CANCEL.pop(cache_key, None)

            # 把完整结果存入缓存（供下次同一路径 30s 内复用）
            entries.sort(key=lambda x: x["size"], reverse=True)
            stats_done = msg.get("stats", {}) if msg.get("phase") == "done" else {}
            payload = {
                "path": str(p),
                "items": entries[:limit],
                "others_size": sum(e["size"] for e in entries[limit:]),
                "truncated": msg.get("truncated", False),
                "elapsed_ms": msg.get("elapsed_ms", 0),
                "stats": stats_done,
                "_items_all": entries,
            }
            _disk_usage_cached_put(cache_key, payload)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _ndjson(obj: dict) -> str:
    """序列化为单行 NDJSON（每行一个 JSON 对象）"""
    return json.dumps(obj, ensure_ascii=False) + "\n"

# ── VSCode 打开 / 路径检测 ──

@router.post("/open-in-vscode")
async def open_in_vscode(path: str = Query(...)):
    """用 VSCode 打开指定路径（文件夹或文件所在目录）"""
    import subprocess, os
    p = os.path.expanduser(path)
    if os.path.isfile(p):
        p = os.path.dirname(p)
    try:
        subprocess.Popen(["code", p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "path": p}
    except FileNotFoundError:
        return {"ok": False, "error": "code 命令未找到。请确认 VSCode 已安装并配置了 code 命令（Cmd+Shift+P → Shell Command: Install 'code' command in PATH）"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/path-exists")
async def path_exists(path: str = Query(...)):
    """检测路径是否存在"""
    import os
    p = os.path.expanduser(path)
    return {"path": p, "exists": os.path.exists(p), "is_dir": os.path.isdir(p) if os.path.exists(p) else False}


@router.post("/open-file-manager")
async def open_file_manager(path: str = Query(...)):
    """用系统文件管理器（Nautilus/xdg-open）打开指定路径，方便删除等操作"""
    import subprocess
    p = _safe_path(path)
    if not p.exists():
        return {"ok": False, "error": "Path not found"}
    target = str(p) if p.is_dir() else str(p.parent)
    try:
        subprocess.Popen(["nautilus", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "path": target}
    except FileNotFoundError:
        try:
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "path": target}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
