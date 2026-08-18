"""M7 环境管理 路由"""

import json, os
from pathlib import Path
from fastapi import APIRouter, Query
from pydantic import BaseModel
from services.env_service import (
    list_envs, get_env_packages, export_requirements, compare_envs,
    get_cuda_info, probe_uv_envs, scan_custom_paths,
)
from database import get_db

router = APIRouter()


@router.get("/list")
async def env_list():
    result = await list_envs()
    result["uv"] = await probe_uv_envs()
    result["cuda"] = await get_cuda_info()
    return result


# ── 自定义环境路径配置 ──

@router.get("/paths")
async def get_env_paths():
    """获取用户配置的环境搜索路径"""
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'env_search_paths'")
    if row:
        try:
            return {"paths": json.loads(row[0]["value"])}
        except Exception:
            pass
    return {"paths": []}


class EnvPathsSave(BaseModel):
    paths: list[str]


@router.post("/paths")
async def save_env_paths(body: EnvPathsSave):
    """保存环境搜索路径"""
    async with get_db() as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('env_search_paths', ?)",
            (json.dumps(body.paths),),
        )
        await db.commit()
    return {"ok": True, "paths": body.paths}


@router.get("/scan")
async def scan_envs(paths: str = Query("")):
    """扫描指定路径下的虚拟环境（路径逗号分隔），若为空则用已保存的配置"""
    if paths:
        path_list = [p.strip() for p in paths.split(",") if p.strip()]
    else:
        async with get_db() as db:
            row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'env_search_paths'")
        if row:
            try:
                path_list = json.loads(row[0]["value"])
            except Exception:
                path_list = []
        else:
            path_list = []

    if not path_list:
        return {"envs": [], "paths": []}

    envs = scan_custom_paths(path_list)

    # 合并备注
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'env_remarks'")
    remarks = {}
    if row:
        try:
            remarks = json.loads(row[0]["value"])
        except Exception:
            pass

    for e in envs:
        e["remark"] = remarks.get(e["path"], "")

    return {"envs": envs, "paths": path_list}


# ── 环境备注 ──

class EnvRemark(BaseModel):
    env_path: str
    remark: str


@router.get("/remarks")
async def get_remarks():
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'env_remarks'")
    if row:
        try:
            return json.loads(row[0]["value"])
        except Exception:
            pass
    return {}


@router.post("/remarks")
async def save_remark(body: EnvRemark):
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'env_remarks'")
        remarks = {}
        if row:
            try:
                remarks = json.loads(row[0]["value"])
            except Exception:
                pass
        if body.remark.strip():
            remarks[body.env_path] = body.remark.strip()
        else:
            remarks.pop(body.env_path, None)
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('env_remarks', ?)",
            (json.dumps(remarks),),
        )
        await db.commit()
    return {"ok": True}


@router.get("/packages")
async def packages(env_path: str = Query(...), type: str = "pip"):
    return await get_env_packages(env_path, type)

@router.get("/requirements")
async def requirements(env_path: str = Query(...)):
    return await export_requirements(env_path)

@router.get("/compare")
async def compare(env1: str, env2: str):
    return await compare_envs(env1, env2)

@router.get("/node/versions")
async def node_versions():
    return await list_envs()


# ── .env 管理 ──

class EnvFileEdit(BaseModel):
    path: str
    content: str

@router.get("/dotenv")
async def read_dotenv(path: str = Query("~/.env")):
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"exists": False, "lines": []}
    lines = []
    with open(p) as f:
        for line in f:
            line = line.rstrip("\n\r")
            masked = line
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                masked = f"{key}=***"
            lines.append({"raw": masked, "is_secret": "=" in line and not line.startswith("#")})
    return {"exists": True, "path": str(p), "lines": lines}

@router.get("/dotenv/raw")
async def read_dotenv_raw(path: str = Query("~/.env")):
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return {"exists": False, "content": ""}
    with open(p) as f:
        return {"exists": True, "path": str(p), "content": f.read()}

@router.post("/dotenv")
async def write_dotenv(body: EnvFileEdit):
    p = Path(body.path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.content)
    return {"ok": True, "path": str(p)}

@router.get("/cuda")
async def cuda_info():
    return await get_cuda_info()
