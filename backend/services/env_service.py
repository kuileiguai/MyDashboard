"""M7 环境管理服务"""

import subprocess
import json
import os
from pathlib import Path


async def list_envs() -> dict:
    result = {
        "python": [],
        "conda": [],
        "node": [],
    }

    # System python
    for py_path in _find_executables("python", "python3"):
        try:
            proc = subprocess.run([py_path, "--version"], capture_output=True, text=True, timeout=3)
            ver = proc.stdout.strip() or proc.stderr.strip()
            result["python"].append({
                "name": py_path,
                "path": py_path,
                "version": ver.replace("Python ", ""),
            })
        except Exception:
            pass

    # Conda
    try:
        proc = subprocess.run(["conda", "env", "list", "--json"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            for env_path in data.get("envs", []):
                name = os.path.basename(env_path)
                result["conda"].append({"name": name, "path": env_path})
    except Exception:
        pass

    # Node
    try:
        proc = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=3)
        result["node"].append({"name": "system", "version": proc.stdout.strip()})
    except Exception:
        pass

    # nvm
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    if nvm_dir.exists():
        for ver_dir in sorted(nvm_dir.iterdir(), reverse=True):
            result["node"].append({"name": ver_dir.name, "path": str(ver_dir), "version": ver_dir.name})

    return result


def _find_executables(*names) -> list:
    found = []
    for path_dir in os.environ.get("PATH", "").split(":"):
        for name in names:
            full = os.path.join(path_dir, name)
            if os.path.isfile(full) and os.access(full, os.X_OK):
                found.append(full)
    return list(dict.fromkeys(found))


async def get_env_packages(env_path: str, type: str = "pip") -> list:
    """查看环境包列表 — env_path 可以是 python 可执行文件或虚拟环境目录"""
    import os

    if type == "pip":
        # 如果 env_path 是目录，找里面的 python 解释器
        python_bin = env_path
        if os.path.isdir(os.path.expanduser(env_path)):
            candidates = [
                os.path.join(env_path, "bin", "python3"),
                os.path.join(env_path, "bin", "python"),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    python_bin = c
                    break

        # 优先用 uv pip list（更快），失败回退到 python -m pip list
        for cmd in [
            ["uv", "pip", "list", "--python", python_bin, "--format", "json"],
            [python_bin, "-m", "pip", "list", "--format", "json"],
        ]:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if proc.returncode == 0:
                    return json.loads(proc.stdout)
            except Exception:
                continue
        return [{"error": f"Cannot list packages for {env_path}"}]

    elif type == "conda":
        try:
            proc = subprocess.run(
                ["conda", "list", "-n", env_path, "--json"],
                capture_output=True, text=True, timeout=10
            )
            return json.loads(proc.stdout)
        except Exception as e:
            return [{"error": str(e)}]
    return []


async def export_requirements(env_path: str) -> str:
    import os
    python_bin = env_path
    if os.path.isdir(os.path.expanduser(env_path)):
        candidates = [
            os.path.join(env_path, "bin", "python3"),
            os.path.join(env_path, "bin", "python"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                python_bin = c
                break

    for cmd in [
        ["uv", "pip", "freeze", "--python", python_bin],
        [python_bin, "-m", "pip", "freeze"],
    ]:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if proc.returncode == 0:
                return proc.stdout
        except Exception:
            continue
    return f"# Error: Cannot export requirements for {env_path}"


async def compare_envs(env1: str, env2: str) -> dict:
    pkg1 = await get_env_packages(env1, "pip")
    pkg2 = await get_env_packages(env2, "pip")
    set1 = {p["name"]: p.get("version", "") for p in pkg1 if "name" in p}
    set2 = {p["name"]: p.get("version", "") for p in pkg2 if "name" in p}
    only_in_1 = {k: v for k, v in set1.items() if k not in set2}
    only_in_2 = {k: v for k, v in set2.items() if k not in set1}
    both = {k: (set1[k], set2[k]) for k in set1 if k in set2 and set1[k] != set2[k]}
    return {"only_in_env1": only_in_1, "only_in_env2": only_in_2, "version_diff": both}


# ── M7: uv 环境探测 ──

async def probe_uv_envs() -> dict:
    """探测 uv 管理的 Python 环境"""
    result = {"available": False, "python_versions": [], "tools": []}
    try:
        # Check uv itself
        proc = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=3)
        if proc.returncode == 0:
            result["available"] = True
            result["version"] = proc.stdout.strip()
    except Exception:
        return result

    # List uv-installed Python versions
    try:
        proc = subprocess.run(["uv", "python", "list"], capture_output=True, text=True, timeout=5)
        for line in proc.stdout.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("cpython-"):
                continue
            if line:
                result["python_versions"].append(line)
    except Exception:
        pass

    # List uv-installed tools
    try:
        proc = subprocess.run(["uv", "tool", "list"], capture_output=True, text=True, timeout=5)
        for line in proc.stdout.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("-"):
                result["tools"].append(line)
    except Exception:
        pass

    # Find .venv directories under home and count uv-managed ones
    result["venvs_found"] = []
    try:
        home = os.path.expanduser("~")
        for root, dirs, files in os.walk(home, followlinks=False):
            if ".venv" in dirs or "venv" in dirs:
                venv_dir = ".venv" if ".venv" in dirs else "venv"
                venv_path = os.path.join(root, venv_dir)
                if os.path.exists(os.path.join(venv_path, "pyvenv.cfg")):
                    uv_managed = os.path.exists(os.path.join(venv_path, "..", "uv.lock")) or \
                                 os.path.exists(os.path.join(venv_path, "..", "pyproject.toml"))
                    result["venvs_found"].append({
                        "path": venv_path,
                        "project": root,
                        "uv_managed": uv_managed,
                    })
                if len(result["venvs_found"]) >= 10:
                    break
            # Limit depth
            if root.count(os.sep) - home.count(os.sep) > 3:
                dirs.clear()
    except Exception:
        pass

    return result


# ── M7-F9: CUDA 兼容信息 ──

async def get_cuda_info() -> dict:
    """探测 CUDA / driver / PyTorch / TensorFlow 版本"""
    result = {
        "cuda": {"available": False, "version": ""},
        "driver": {"version": ""},
        "pytorch": {"installed": False, "version": "", "cuda_available": False},
        "tensorflow": {"installed": False, "version": ""},
    }

    # nvidia-smi
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            result["driver"]["version"] = proc.stdout.strip()
    except Exception:
        pass

    # nvcc --version
    try:
        proc = subprocess.run(["nvcc", "--version"], capture_output=True, text=True, timeout=5)
        for line in proc.stdout.split("\n"):
            if "release" in line:
                result["cuda"]["version"] = line.split("release")[-1].strip().rstrip(",")
                result["cuda"]["available"] = True
                break
    except Exception:
        pass

    # Try getting CUDA version from nvidia-smi
    if not result["cuda"]["version"]:
        try:
            proc = subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, timeout=5,
            )
            for line in proc.stdout.split("\n"):
                if "CUDA Version:" in line:
                    result["cuda"]["version"] = line.split("CUDA Version:")[-1].strip()
                    result["cuda"]["available"] = True
                    break
        except Exception:
            pass

    # PyTorch
    try:
        proc = subprocess.run(
            ["python3", "-c",
             "import torch; print(f'{torch.__version__}|{torch.cuda.is_available()}|{torch.version.cuda or \"\"}')"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            parts = proc.stdout.strip().split("|")
            result["pytorch"] = {
                "installed": True,
                "version": parts[0] if len(parts) > 0 else "",
                "cuda_available": parts[1] == "True" if len(parts) > 1 else False,
                "cuda_version": parts[2] if len(parts) > 2 else "",
            }
    except Exception:
        pass

    # TensorFlow
    try:
        proc = subprocess.run(
            ["python3", "-c", "import tensorflow as tf; print(tf.__version__)"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            result["tensorflow"] = {"installed": True, "version": proc.stdout.strip()}
    except Exception:
        pass

    return result



# ── 自定义环境路径扫描 ──

def get_custom_env_paths() -> list[str]:
    """从 settings 读取用户配置的环境搜索路径"""
    import asyncio, json
    try:
        from database import get_db
        async def _get():
            async with get_db() as db:
                row = await db.execute_fetchall("SELECT value FROM settings WHERE key = 'env_search_paths'")
            if row:
                return json.loads(row[0]["value"])
            return []
        return asyncio.run(_get())
    except Exception:
        return []


def scan_custom_paths(paths: list[str]) -> list[dict]:
    """扫描指定路径下所有虚拟环境（.venv / venv / 含 pyvenv.cfg 的目录）"""
    results = []
    seen = set()

    for root_path in paths:
        p = Path(os.path.expanduser(root_path))
        if not p.exists():
            continue
        # 直接检查这个路径本身是否是 venv
        if os.path.exists(p / "pyvenv.cfg") or os.path.exists(p / "bin" / "python"):
            if str(p) not in seen:
                seen.add(str(p))
                results.append(_describe_venv(p, p.name, p))
            continue
        # 扫描子目录
        try:
            for entry in p.iterdir():
                if not entry.is_dir():
                    continue
                ep = Path(entry)
                if os.path.exists(ep / "pyvenv.cfg") or os.path.exists(ep / "bin" / "python"):
                    if str(ep) not in seen:
                        seen.add(str(ep))
                        results.append(_describe_venv(ep, ep.name, p))
                # 也检查 .venv 子目录
                elif os.path.exists(ep / ".venv" / "pyvenv.cfg"):
                    vp = ep / ".venv"
                    if str(vp) not in seen:
                        seen.add(str(vp))
                        results.append(_describe_venv(vp, ep.name, p))
                elif os.path.exists(ep / "venv" / "pyvenv.cfg"):
                    vp = ep / "venv"
                    if str(vp) not in seen:
                        seen.add(str(vp))
                        results.append(_describe_venv(vp, ep.name, p))
        except PermissionError:
            pass

    # 按项目名排序
    results.sort(key=lambda x: x["project_name"])
    return results


def _describe_venv(venv_path: Path, project_name: str, parent: Path) -> dict:
    """描述一个虚拟环境"""
    py_ver = ""
    python_bin = venv_path / "bin" / "python"
    if python_bin.exists():
        try:
            proc = subprocess.run(
                [str(python_bin), "--version"],
                capture_output=True, text=True, timeout=5,
            )
            py_ver = proc.stdout.strip() or proc.stderr.strip()
            py_ver = py_ver.replace("Python ", "")
        except Exception:
            pass

    size = _dir_size(str(venv_path))

    return {
        "name": project_name,
        "path": str(venv_path),
        "parent": str(parent),
        "project_name": project_name,
        "python_version": py_ver,
        "size_bytes": size,
        "size_human": _fmt_size(size),
    }


def _dir_size(path: str) -> int:
    """计算目录大小，限制深度和时间"""
    import time, signal
    total = 0
    start = time.time()
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
            # 超时保护：超过 5 秒停止
            if time.time() - start > 5:
                break
    except Exception:
        pass
    return total


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"
