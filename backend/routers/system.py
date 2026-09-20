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
    """打开 GPU 进程的工作目录（文件管理器：nautilus → xdg-open）。

    /proc/<pid>/cwd 需要 ptrace 权限，只有同用户进程可读；进程属于 root/其他账号或
    位于容器等命名空间时读不到，此时按命令行（cmdline/exe）推断目录并标注 guessed，
    同时把真实失败原因回传前端。
    """
    import os, subprocess
    detail = get_gpu_process_detail(pid)
    if not detail.get("found"):
        return {"ok": False, "error": detail.get("error") or "进程不存在或已退出"}

    cwd = detail.get("cwd") or ""
    guessed = False
    if cwd and os.path.isdir(cwd):
        target = cwd
    else:
        # cwd 不可读或目录已不存在 → 退到按命令行推断的目录
        target = detail.get("cwd_guess") or ""
        guessed = True
        if not target:
            if cwd:
                reason = f"工作目录已不存在: {cwd}"
            else:
                reason = detail.get("cwd_error_text") or "无法获取进程工作目录"
            return {"ok": False, "error": reason, "cwd_error": detail.get("cwd_error", "")}

    if not os.path.isdir(target):
        return {"ok": False, "error": f"目录不存在: {target}"}

    for opener in (["nautilus", target], ["xdg-open", target]):
        try:
            subprocess.Popen(opener, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            resp = {"ok": True, "path": target}
            if guessed:
                resp["guessed"] = True
                resp["note"] = detail.get("cwd_guess_note", "")
            return resp
        except FileNotFoundError:
            continue
    return {"ok": False, "error": "没有可用的文件管理器"}
