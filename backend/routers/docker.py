"""Docker 管理 REST 路由"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.docker_service import (
    docker_available, list_containers, container_action, container_logs,
    container_inspect, container_stats, list_images, image_action, pull_image,
    list_compose_projects, compose_action, list_volumes, volume_action,
    list_networks, network_action, system_info, system_df, system_prune,
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


@router.post("/images/{iid}/{action}")
async def image_op(iid: str, action: str):
    return image_action(iid, action)


# ── Compose ──

@router.get("/compose")
async def compose_projects(base: str = ""):
    return {"projects": list_compose_projects(base)}


class ComposeBody(BaseModel):
    project_dir: str
    action: str


@router.post("/compose/action")
async def compose_op(body: ComposeBody):
    return compose_action(body.project_dir, body.action)


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
