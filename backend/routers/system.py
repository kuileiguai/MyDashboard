"""M5 系统监控 REST 路由"""

from fastapi import APIRouter, Query
from services.monitor_service import (
    get_snapshot, get_disk_top, get_all_gpu_processes,
    get_gpu_process_detail,
)
from services.dependency_service import check_dependencies, install_missing, get_missing_packages

router = APIRouter()


@router.get("/overview")
async def system_overview():
    return get_snapshot()


@router.get("/disk-top")
async def disk_top(path: str = "~", n: int = 10):
    return await get_disk_top(path, n)


# ── 依赖管理 ──

@router.get("/dependencies")
async def dependencies_check():
    """检查系统工具安装状态"""
    return check_dependencies()


@router.get("/dependencies/missing")
async def dependencies_missing():
    """仅返回缺失的包名"""
    return {"missing": get_missing_packages()}


@router.post("/dependencies/install")
async def dependencies_install(use_pkexec: bool = True):
    """一键安装缺失的系统依赖（pkexec 弹 GUI 密码框）"""
    return install_missing(pkexec=use_pkexec)


# ── GPU 进程详情 ──

@router.get("/gpu/processes")
async def gpu_processes():
    """所有 GPU 卡上的进程（含进程名/命令行/工作目录）"""
    return {"processes": get_all_gpu_processes()}


@router.get("/gpu/proc/{pid}")
async def gpu_proc_detail(pid: int):
    """单个 GPU 进程详细启动信息（含父进程链）"""
    return get_gpu_process_detail(pid)


@router.post("/gpu/proc/{pid}/open-folder")
async def gpu_proc_open_folder(pid: int):
    """打开 GPU 进程的工作目录（用文件管理器/nautilus）"""
    import os, subprocess
    detail = get_gpu_process_detail(pid)
    if not detail.get("found") or not detail.get("cwd"):
        return {"ok": False, "error": "无法获取进程工作目录"}
    cwd = detail["cwd"]
    if not os.path.isdir(cwd):
        return {"ok": False, "error": f"工作目录不存在: {cwd}"}
    # 优先 nautilus，回退 xdg-open
    for opener in (["nautilus", cwd], ["xdg-open", cwd]):
        try:
            subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "path": cwd}
        except FileNotFoundError:
            continue
    return {"ok": False, "error": "没有可用的文件管理器"}
