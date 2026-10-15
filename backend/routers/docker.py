"""Docker 管理 REST 路由"""

import json

from fastapi import APIRouter, Query
from pydantic import BaseModel

from database import get_db
from services.docker_service import (
    docker_available, list_containers, container_action, container_logs,
    container_inspect, container_stats, list_images, image_action, pull_image,
    save_image, default_save_dir, list_compose_projects, verify_compose_projects,
    compose_action, read_compose_file, write_compose_file,
    list_volumes, volume_action, list_networks, network_action,
    system_info, system_df, system_prune,
)

router = APIRouter()


@router.get("/available")
async def available():
    return docker_available()


# ── 容器 ──

@router.get("/containers")
async def containers(all: bool = False):
    return {"containers": list_containers(all)}


@router.post("/containers/{cid}/{action}")
async def container_op(cid: str, action: str):
    return container_action(cid, action)


@router.get("/containers/{cid}/logs")
async def container_log(cid: str, tail: int = 200):
    return {"logs": container_logs(cid, tail)}


@router.get("/containers/{cid}/inspect")
async def container_detail(cid: str):
    return container_inspect(cid)


@router.get("/stats")
async def stats():
    return {"stats": container_stats()}


# ── 镜像 ──

@router.get("/images")
async def images():
    return {"images": list_images()}


class PullBody(BaseModel):
    name: str
    tag: str = "latest"


@router.post("/images/pull")
async def image_pull(body: PullBody):
    return pull_image(body.name, body.tag)


@router.get("/images/save/default-dir")
async def image_save_default_dir():
    return {"dir": default_save_dir()}


class SaveImageBody(BaseModel):
    images: list[str]
    output_dir: str = ""
    filename: str = ""
    compress: bool = False


@router.post("/images/save")
async def image_save(body: SaveImageBody):
    """docker save 导出镜像到指定目录"""
    return save_image(body.images, body.output_dir, body.filename, body.compress)


@router.post("/images/{iid}/{action}")
async def image_op(iid: str, action: str):
    return image_action(iid, action)


# ── Compose ──

_SETTINGS_KEY = "compose_projects"


async def _load_compose_records() -> list[dict]:
    async with get_db() as db:
        rows = await db.execute_fetchall("SELECT value FROM settings WHERE key = ?", (_SETTINGS_KEY,))
    if not rows:
        return []
    try:
        data = json.loads(rows[0]["value"])
    except Exception:
        return []
    return [p for p in data if isinstance(p, dict) and p.get("path")] if isinstance(data, list) else []


async def _save_compose_records(records: list[dict]) -> None:
    slim = [{"name": p.get("name", ""), "path": p["path"], "compose_file": p.get("compose_file", "")}
            for p in records]
    async with get_db() as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                         (_SETTINGS_KEY, json.dumps(slim, ensure_ascii=False)))
        await db.commit()


@router.get("/compose")
async def compose_projects(base: str = "", scan: bool = False):
    """scan=true 时扫描 base 目录并把结果并入记录；否则仅复核已记录的 compose 是否还在"""
    records = await _load_compose_records()
    by_path = {p["path"]: p for p in records}
    scanned = 0
    if scan:
        for proj in list_compose_projects(base):
            item = by_path.get(proj["path"], {})
            item.update(proj)
            by_path[proj["path"]] = item
            scanned += 1
        await _save_compose_records(list(by_path.values()))
    projects = verify_compose_projects(list(by_path.values()))
    projects.sort(key=lambda p: (not p["exists"], p.get("name", "")))
    return {"projects": projects, "records": len(by_path), "scanned": scanned}


class ComposeBody(BaseModel):
    project_dir: str
    action: str


@router.post("/compose/action")
async def compose_op(body: ComposeBody):
    return compose_action(body.project_dir, body.action)


class ComposeForgetBody(BaseModel):
    path: str


@router.post("/compose/forget")
async def compose_forget(body: ComposeForgetBody):
    records = await _load_compose_records()
    remaining = [p for p in records if p["path"] != body.path]
    await _save_compose_records(remaining)
    return {"ok": True, "removed": len(records) - len(remaining)}


@router.get("/compose/file")
async def compose_file_read(path: str = Query(...)):
    return read_compose_file(path)


class ComposeFileBody(BaseModel):
    path: str
    content: str


@router.post("/compose/file")
async def compose_file_write(body: ComposeFileBody):
    return write_compose_file(body.path, body.content)


# ── 卷 ──

@router.get("/volumes")
async def volumes():
    return {"volumes": list_volumes()}


class VolumeBody(BaseModel):
    name: str
    action: str


@router.post("/volumes/action")
async def volume_op(body: VolumeBody):
    return volume_action(body.name, body.action)


# ── 网络 ──

@router.get("/networks")
async def networks():
    return {"networks": list_networks()}


class NetworkBody(BaseModel):
    name: str
    action: str
    driver: str = "bridge"


@router.post("/networks/action")
async def network_op(body: NetworkBody):
    return network_action(body.name, body.action, body.driver)


# ── 系统级 ──

@router.get("/system")
async def sys_info():
    return {"info": system_info(), "df": system_df()}


@router.post("/system/prune")
async def sys_prune():
    return system_prune()
