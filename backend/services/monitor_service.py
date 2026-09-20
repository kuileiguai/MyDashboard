"""M5 系统监控采样服务"""

import time
import os
import asyncio
from collections import deque
from config import MONITOR_HISTORY_POINTS, MONITOR_INTERVAL, MONITOR_IDLE_INTERVAL
import psutil

# GPU 尝试导入
try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    GPU_AVAILABLE = False

# 环形缓冲
_history: deque = deque(maxlen=MONITOR_HISTORY_POINTS)
_subscribers: list = []
_last_sample_time = 0


def get_snapshot() -> dict:
    """返回当前一次性全量快照"""
    return _sample_now()


def _sample_now() -> dict:
    snap: dict = {
        "ts": time.time(),
    }

    # CPU
    cpu_pct = psutil.cpu_percent(interval=0.1, percpu=True)
    snap["cpu"] = {
        "total": round(sum(cpu_pct) / len(cpu_pct), 1) if cpu_pct else 0,
        "per_core": [round(x, 1) for x in cpu_pct],
        "count": len(cpu_pct),
    }

    # Load
    la = os.getloadavg()
    snap["load"] = {"load1": round(la[0], 2), "load5": round(la[1], 2), "load15": round(la[2], 2)}

    # Memory
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    snap["memory"] = {
        "total": mem.total,
        "used": mem.used,
        "percent": mem.percent,
        "available": mem.available,
    }
    snap["swap"] = {
        "total": swap.total,
        "used": swap.used,
        "percent": swap.percent,
    }

    # Disk
    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "mountpoint": part.mountpoint,
                "device": part.device,
                "total": usage.total,
                "used": usage.used,
                "percent": usage.percent,
            })
        except Exception:
            pass
    snap["disks"] = disks

    # Network
    net = psutil.net_io_counters()
    snap["network"] = {
        "bytes_sent": net.bytes_sent,
        "bytes_recv": net.bytes_recv,
    }

    # GPU
    if GPU_AVAILABLE:
        try:
            gpus = []
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpus.append({
                    "index": i,
                    "name": pynvml.nvmlDeviceGetName(handle) if hasattr(pynvml, "nvmlDeviceGetName") else f"GPU {i}",
                    "memory_total": info.total,
                    "memory_used": info.used,
                    "memory_percent": round(info.used / info.total * 100, 1) if info.total else 0,
                    "gpu_util": util.gpu,
                    "temperature": 0,
                    "fan_speed": 0,
                })
                # Temperature (may fail on some cards)
                try:
                    gpus[-1]["temperature"] = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    pass
                # Fan
                try:
                    gpus[-1]["fan_speed"] = pynvml.nvmlDeviceGetFanSpeed(handle)
                except Exception:
                    pass
                # GPU processes（计算 + 图形进程）
                procs = []
                try:
                    compute = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                    for p in compute:
                        procs.append({"pid": p.pid, "memory_used": p.usedGpuMemory, "type": "compute"})
                except Exception:
                    pass
                try:
                    graphics = pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
                    for p in graphics:
                        procs.append({"pid": p.pid, "memory_used": p.usedGpuMemory, "type": "graphics"})
                except Exception:
                    pass
                # 补充进程详细信息（进程名/命令行/cwd/启动时间/用户）
                for p in procs:
                    _enrich_process_info(p)
                gpus[-1]["processes"] = procs

            snap["gpu"] = {"available": True, "devices": gpus}
        except Exception:
            snap["gpu"] = {"available": False, "error": "GPU query failed"}
    else:
        snap["gpu"] = {"available": False, "reason": "pynvml not available or no NVIDIA GPU"}

    return snap


async def _monitor_loop():
    """后台采样任务，按活跃订阅者数量调整采样间隔"""
    global _last_sample_time
    while True:
        now = time.time()
        interval = MONITOR_INTERVAL if _subscribers else MONITOR_IDLE_INTERVAL
        if now - _last_sample_time >= interval:
            snap = _sample_now()
            _history.append({"ts": now, **snap})

            if _subscribers:
                dead = []
                for ws in _subscribers:
                    try:
                        await ws.send_json(snap)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    if ws in _subscribers:
                        _subscribers.remove(ws)
            _last_sample_time = now

        await asyncio.sleep(max(0.5, min(interval, 2.0)))


def get_history(max_points: int = 150) -> list:
    return list(_history)[-max_points:]


def add_monitor_subscriber(ws):
    _subscribers.append(ws)


def remove_monitor_subscriber(ws):
    if ws in _subscribers:
        _subscribers.remove(ws)


async def get_disk_top(path: str = "~", n: int = 10) -> list[dict]:
    """扫描目录找出最大的文件/目录"""
    import os
    target = os.path.expanduser(path)
    entries = []
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        size = _du_size(entry.path)
                    else:
                        size = entry.stat().st_size
                    entries.append({"name": entry.name, "path": entry.path, "size": size, "is_dir": entry.is_dir()})
                except Exception:
                    pass
    except Exception:
        pass
    entries.sort(key=lambda x: x["size"], reverse=True)
    return entries[:n]


def _du_size(path: str) -> int:
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


# ── GPU 进程详情服务 ──

# 这些系统目录即便存在也不是用户的工程目录，推断"启动目录"时跳过
_SYSTEM_PATHS = {
    "/", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32",
    "/etc", "/boot", "/proc", "/sys", "/dev", "/run", "/snap", "/lost+found",
}


def _is_system_path(path: str) -> bool:
    p = path.rstrip("/") or "/"
    if p in _SYSTEM_PATHS:
        return True
    return any(p.startswith(root + "/") for root in _SYSTEM_PATHS if root != "/")


def guess_work_dir(cmdline: list, exe: str = "") -> tuple[str, str]:
    """cwd 不可读时，从命令行/可执行文件推断进程的工程目录。

    跨用户（进程属于 root、或位于其他命名空间如容器内）时 /proc/<pid>/cwd 的
    readlink 需要 ptrace 权限，会 EACCES；而同期的 cmdline / exe 仍可读——这正是
    "能看到是哪个脚本启动的，却打不开工作目录"的原因。

    取命令行里第一个"存在的、非系统目录的绝对路径"：是目录就用它，是文件就用其父目录。
    返回 (path, note)；path 为空表示推断不出来。
    """
    for arg in cmdline or []:
        if not arg.startswith("/") or arg.startswith("-") or _is_system_path(arg):
            continue
        if os.path.isdir(arg):
            return arg, f"cwd 不可读，按命令行参数推断: {arg}"
        if os.path.isfile(arg):
            parent = os.path.dirname(arg)
            if parent and not _is_system_path(parent) and os.path.isdir(parent):
                return parent, f"cwd 不可读，按命令行中的文件推断: {arg} → {parent}"
    # 兜底：可执行文件自身（如 /opt/myapp/bin/train），但跳过 bin/sbin 这类目录
    if exe.startswith("/") and not _is_system_path(exe):
        parent = os.path.dirname(exe)
        if (
            parent
            and os.path.basename(parent) not in ("bin", "sbin", "libexec", "lib", "lib64")
            and os.path.isdir(parent)
        ):
            return parent, f"cwd 不可读，按可执行文件推断: {exe} → {parent}"
    return "", ""


def _cwd_error_text(exc: Exception) -> str:
    """把 cwd 读取失败翻译成能给用户看的原因"""
    if isinstance(exc, psutil.AccessDenied):
        return (
            "无权读取该进程的工作目录（/proc/<pid>/cwd 需要 ptrace 权限）："
            "该进程属于其他用户（如 root）或位于其他命名空间（如容器内）。"
            "可复制启动命令，或让后端以相同用户/root 运行。"
        )
    if isinstance(exc, psutil.ZombieProcess):
        return "该进程处于僵尸态，无法读取工作目录"
    if isinstance(exc, psutil.NoSuchProcess):
        return "该进程已退出"
    return f"读取工作目录失败: {exc}"


def _enrich_process_info(proc_info: dict):
    """从 /proc 和 psutil 补充进程详细信息"""
    pid = proc_info.get("pid", 0)
    if not pid:
        return
    try:
        p = psutil.Process(pid)
        proc_info["name"] = p.name()
        proc_info["username"] = p.username()
        proc_info["create_time"] = p.create_time()
        try:
            proc_info["cwd"] = p.cwd()
        except Exception:
            proc_info["cwd"] = ""
        try:
            proc_info["cmdline"] = " ".join(p.cmdline())
        except Exception:
            proc_info["cmdline"] = ""
    except psutil.NoSuchProcess:
        proc_info["name"] = "(已退出)"
        proc_info["username"] = ""
        proc_info["cwd"] = ""
        proc_info["cmdline"] = ""
    except Exception:
        pass


def get_gpu_process_detail(pid: int) -> dict:
    """获取单个 GPU 进程的详细启动信息（含父进程链）"""
    result = {"pid": pid, "found": False}
    try:
        p = psutil.Process(pid)
        result["found"] = True
        result["name"] = p.name()
        result["username"] = p.username()
        result["create_time"] = p.create_time()
        try:
            result["cwd"] = p.cwd()
        except Exception as e:
            # 跨用户/容器时 /proc/<pid>/cwd 会 EACCES，别把原因吞掉
            result["cwd"] = ""
            result["cwd_error"] = type(e).__name__
            result["cwd_error_text"] = _cwd_error_text(e)
        try:
            result["exe"] = p.exe()
        except Exception:
            result["exe"] = ""
        try:
            result["cmdline"] = p.cmdline()
            result["cmdline_str"] = " ".join(p.cmdline())
        except Exception:
            result["cmdline"] = []
            result["cmdline_str"] = ""
        try:
            result["memory_percent"] = round(p.memory_percent(), 2)
        except Exception:
            result["memory_percent"] = 0
        try:
            result["status"] = p.status()
        except Exception:
            result["status"] = ""
        # cwd 读不到（跨用户/容器）时，按命令行推断一个能打开的目录
        if not result.get("cwd"):
            guess, note = guess_work_dir(result.get("cmdline") or [], result.get("exe", ""))
            if guess:
                result["cwd_guess"] = guess
                result["cwd_guess_note"] = note
        # 父进程链
        chain = []
        cur = p
        for _ in range(10):
            try:
                chain.append({
                    "pid": cur.pid,
                    "name": cur.name(),
                    "cmdline": " ".join(cur.cmdline()[:3])[:200],
                })
                cur = cur.parent()
                if cur is None:
                    break
            except Exception:
                break
        result["parent_chain"] = chain
    except psutil.NoSuchProcess:
        result["error"] = "进程不存在或已退出"
    except Exception as e:
        result["error"] = str(e)
    return result


def get_all_gpu_processes() -> list[dict]:
    """聚合所有 GPU 卡上的进程（去重，附卡号信息）"""
    if not GPU_AVAILABLE:
        return []
    result = []
    seen = set()
    try:
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle) if hasattr(pynvml, "nvmlDeviceGetName") else f"GPU {i}"
            procs = []
            try:
                for p in pynvml.nvmlDeviceGetComputeRunningProcesses(handle):
                    procs.append({"pid": p.pid, "memory_used": p.usedGpuMemory, "type": "compute"})
            except Exception:
                pass
            try:
                for p in pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle):
                    procs.append({"pid": p.pid, "memory_used": p.usedGpuMemory, "type": "graphics"})
            except Exception:
                pass
            for p in procs:
                _enrich_process_info(p)
                p["gpu_index"] = i
                p["gpu_name"] = name
                key = p["pid"]
                if key in seen:
                    continue
                seen.add(key)
                result.append(p)
    except Exception:
        pass
    return result
