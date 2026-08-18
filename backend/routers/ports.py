"""M3 端口监控 路由"""

import json
import time
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db
from services.port_service import (
    get_listening_ports, get_port_detail, get_all_processes,
    kill_process, get_systemd_services, systemd_action, detect_zombies,
)

router = APIRouter()


@router.get("/ports")
async def list_ports():
    return await get_listening_ports()


@router.get("/ports/{port}/detail")
async def port_detail(port: int):
    return await get_port_detail(port)


@router.delete("/ports/{pid}/kill")
async def kill_proc(pid: int, sig: str = "term"):
    return await kill_process(pid, sig)


@router.get("/processes")
async def list_processes(sort: str = "cpu", q: str = ""):
    return await get_all_processes(sort, q)


# ── M3-F9: systemd 服务管理 ──

class SystemdAction(BaseModel):
    service_name: str
    action: str  # start/stop/restart/enable/disable
    scope: str = "user"  # system or user


@router.get("/systemd")
async def list_systemd_services(scope: str = "user"):
    return await get_systemd_services(scope)


@router.post("/systemd")
async def systemd_act(body: SystemdAction):
    return await systemd_action(body.service_name, body.action, body.scope)


# ── M3-F10: 僵尸/孤儿进程识别 ──

@router.get("/processes/zombies")
async def list_zombies():
    """标记并返回疑似僵尸/孤儿进程"""
    return await detect_zombies()


# ── M3-F11: 端口快照对比 ──

@router.get("/ports/snapshot")
async def take_snapshot():
    """获取当前端口快照并存入 DB"""
    ports = await get_listening_ports()
    snap = {"ts": time.time(), "ports": ports}
    async with get_db() as db:
        await db.execute(
            "INSERT INTO port_snapshots (snapshot_data) VALUES (?)",
            (json.dumps(snap),),
        )
        await db.commit()
    return snap


@router.get("/ports/snapshots")
async def list_snapshots(limit: int = 10):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT * FROM port_snapshots ORDER BY id DESC LIMIT ?", (limit,)
        )
    return [{"id": r["id"], "created_at": r["created_at"],
             "data": json.loads(r["snapshot_data"])} for r in rows]


@router.get("/ports/snapshots/compare")
async def compare_snapshots(id1: int = 0, id2: int = 0):
    """对比两个快照的端口差异"""
    async with get_db() as db:
        if id1 and id2:
            r1 = await db.execute_fetchall("SELECT * FROM port_snapshots WHERE id = ?", (id1,))
            r2 = await db.execute_fetchall("SELECT * FROM port_snapshots WHERE id = ?", (id2,))
        else:
            rows = await db.execute_fetchall("SELECT * FROM port_snapshots ORDER BY id DESC LIMIT 2")
            if len(rows) < 2:
                return {"error": "Need at least 2 snapshots. Take some snapshots first."}
            r1, r2 = [rows[1]], [rows[0]]

    if not r1 or not r2:
        raise HTTPException(404, "Snapshots not found")

    snap1 = json.loads(r1[0]["snapshot_data"])
    snap2 = json.loads(r2[0]["snapshot_data"])

    ports1 = {(p["port"], p["protocol"]): p for p in snap1.get("ports", [])}
    ports2 = {(p["port"], p["protocol"]): p for p in snap2.get("ports", [])}

    new_ports = [p for k, p in ports2.items() if k not in ports1]
    gone_ports = [p for k, p in ports1.items() if k not in ports2]
    same_ports = [p2 for k, p2 in ports2.items() if k in ports1]

    return {
        "snapshot1": {"id": r1[0]["id"], "ts": snap1["ts"], "count": len(snap1.get("ports", []))},
        "snapshot2": {"id": r2[0]["id"], "ts": snap2["ts"], "count": len(snap2.get("ports", []))},
        "new_ports": new_ports,
        "gone_ports": gone_ports,
        "unchanged": len(same_ports),
    }
