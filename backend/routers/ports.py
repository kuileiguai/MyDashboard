"""M3 端口监控 路由"""

import json
import time
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_db
from services.port_service import (
    get_listening_ports, get_port_detail, get_all_processes,
    kill_process, get_systemd_services, systemd_action, detect_zombies,
    load_port_config, save_port_config, load_port_remarks, save_port_remark,
    list_snapshots, take_snapshot, list_alerts, mark_alerts_read, clear_alerts,
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

class PortConfig(BaseModel):
    watch_ports: list[int] | None = None
    auto_snapshot: bool | None = None
    interval_min: int | None = None
    alert_new: bool | None = None
    alert_gone: bool | None = None


@router.get("/ports/config")
async def get_port_config():
    """关注端口 / 自动快照 / 告警开关"""
    return await load_port_config()


@router.post("/ports/config")
async def set_port_config(body: PortConfig):
    return await save_port_config(body.model_dump(exclude_none=True))


class PortRemark(BaseModel):
    port: int
    protocol: str = ""
    remark: str = ""


@router.get("/ports/remarks")
async def get_port_remarks():
    return await load_port_remarks()


@router.post("/ports/remarks")
async def set_port_remark(body: PortRemark):
    """给端口写备注（key = 端口/协议状态，留空即清除）"""
    key = f"{body.port}/{body.protocol}".rstrip("/")
    return {"ok": True, "remarks": await save_port_remark(key, body.remark)}


@router.get("/ports/alerts")
async def get_port_alerts(limit: int = 100, unread_only: bool = False):
    return await list_alerts(limit, unread_only)


class AlertIds(BaseModel):
    ids: list[int] | None = None
    all: bool = False


@router.post("/ports/alerts/read")
async def read_port_alerts(body: AlertIds):
    return await mark_alerts_read(body.ids, body.all)


@router.delete("/ports/alerts")
async def delete_port_alerts(body: AlertIds):
    return await clear_alerts(body.ids, body.all)


@router.get("/ports/snapshot")
async def take_snapshot_api():
    """获取当前端口快照并存入 DB，同时与上一条快照对比产生告警"""
    return await take_snapshot("manual")


@router.get("/ports/snapshots")
async def list_snapshots_api(limit: int = 50):
    return await list_snapshots(limit)


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
