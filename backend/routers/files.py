"""M2 文件管理 路由"""

import os, shutil, json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
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
