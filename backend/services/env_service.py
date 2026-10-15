"""M7 环境管理服务"""

import subprocess
import json
import os
import re
import shutil
from pathlib import Path


def _run_capture(cmd, timeout=5) -> tuple[int, str]:
    """执行命令并返回 (returncode, 合并输出)"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except Exception:
        return -1, ""


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _dir_size_fast(path: str, timeout: int = 15) -> int:
    """用 du 统计目录大小（比 Python 遍历快），失败回退 _dir_size"""
    p = Path(os.path.expanduser(str(path)))
    if not p.is_dir():
        return 0
    try:
        proc = subprocess.run(["du", "-sbx", str(p)], capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0 and proc.stdout:
            return int(proc.stdout.split()[0])
    except Exception:
        pass
    return _dir_size(str(p))


def _cache_entry(label: str, path: str) -> dict | None:
    p = Path(os.path.expanduser(path))
    if not p.is_dir():
        return None
    size = _dir_size_fast(str(p))
    return {"name": label, "path": str(p), "size_bytes": size, "size_human": _fmt_size(size)}


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



# ── Java 环境探测 ──

JAVA_SCAN_ROOTS = (
    "/usr/lib/jvm", "/usr/java", "/opt/java", "/opt/jdk",
    "~/.jdks", "~/.sdkman/candidates/java",
    "/Library/Java/JavaVirtualMachines",
)


def _parse_java_version(text: str) -> str:
    """从 java -version 输出里取版本号（第一行引号内内容）"""
    line = _first_line(text)
    m = re.search(r'"([^"]+)"', line)
    if m:
        return m.group(1)
    return re.sub(r"^(openjdk|java|javac)\s+version\s*", "", line, flags=re.I).strip()


def _parse_release(jdk_dir: Path) -> dict:
    """解析 JDK 目录下的 release 文件（比启动 java 快很多）"""
    data: dict[str, str] = {}
    rel = Path(jdk_dir) / "release"
    if not rel.is_file():
        return data
    try:
        for line in rel.read_text(errors="replace").splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                data[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return data


def _describe_jdk(base: Path) -> dict:
    rel = _parse_release(base)
    version = rel.get("JAVA_VERSION", "")
    if not version:
        _, out = _run_capture([str(base / "bin" / "java"), "-version"], timeout=4)
        version = _parse_java_version(out)
    return {
        "name": base.name,
        "path": str(base),
        "version": version,
        "vendor": rel.get("IMPLEMENTOR") or rel.get("IMPLEMENTOR_VENDOR") or "",
        "arch": rel.get("OS_ARCH", ""),
    }


async def probe_java_envs() -> dict:
    """探测 Java 环境：当前 JVM / JAVA_HOME / 已安装 JDK / 构建工具 / 本地仓库体积"""
    result = {
        "available": False, "version": "", "runtime": "", "javac_version": "",
        "java_home": "", "jdks": [], "build_tools": [], "caches": [],
    }

    java_home = os.environ.get("JAVA_HOME", "").strip()
    result["java_home"] = java_home
    try:
        jh_key = str(Path(os.path.expanduser(java_home)).resolve()) if java_home else ""
    except OSError:
        jh_key = java_home

    rc, out = _run_capture(["java", "-version"], timeout=5)
    if rc == 0 and out:
        result["available"] = True
        result["runtime"] = _first_line(out)
        result["version"] = _parse_java_version(out)

    rc2, out2 = _run_capture(["javac", "-version"], timeout=5)
    if rc2 == 0 and out2:
        result["javac_version"] = _first_line(out2).replace("javac ", "").strip()

    # 已安装 JDK
    roots = [Path(os.path.expanduser(r)) for r in JAVA_SCAN_ROOTS]
    if java_home:
        roots.insert(0, Path(os.path.expanduser(java_home)))
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = [c for c in sorted(root.iterdir()) if c.is_dir()]
        except (PermissionError, OSError):
            children = []
        for child in [root] + children:
            base = child
            home = child / "Contents" / "Home"          # macOS 布局
            if home.is_dir():
                base = home
            if not (base / "bin" / "java").is_file():
                continue
            try:
                key = str(base.resolve())
            except OSError:
                key = str(base)
            if key in seen:
                continue
            seen.add(key)
            info = _describe_jdk(base)
            info["is_java_home"] = bool(jh_key) and key == jh_key
            result["jdks"].append(info)
            if len(result["jdks"]) >= 30:
                break
        if len(result["jdks"]) >= 30:
            break

    # 构建工具
    for name, args in (("Maven", ["mvn", "-v"]), ("Gradle", ["gradle", "-v"])):
        rc3, out3 = _run_capture(args, timeout=8)
        if rc3 != 0 or not out3:
            continue
        # 去掉 Maven 版本后面的 commit 串：Apache Maven 3.9.16 (abc...) → Apache Maven 3.9.16
        version = _first_line(out3).split(" (")[0].strip()
        home_path = ""
        for line in out3.splitlines():
            m = re.match(r"^(?:Maven|Gradle) home:\s*(.+)$", line.strip(), flags=re.I)
            if m:
                home_path = m.group(1).strip()
                break
        result["build_tools"].append({
            "name": name,
            "version": version,
            "path": home_path or shutil.which(args[0]) or "",
        })

    # 本地仓库 / 缓存体积
    for label, path in (
        ("Maven 本地仓库", "~/.m2/repository"),
        ("Gradle 缓存", "~/.gradle/caches"),
        ("Gradle Wrapper", "~/.gradle/wrapper/dists"),
    ):
        entry = _cache_entry(label, path)
        if entry:
            result["caches"].append(entry)

    return result


# ── Go 环境探测 ──

GO_SCAN_ROOTS = ("/usr/local", "/usr/lib", "/opt", "~/.goenv/versions", "~/.sdkman/candidates/go")
GO_DIR_RE = re.compile(r"^go([-.\d]|$)", re.I)


def _describe_go(go_root: Path) -> dict:
    version = ""
    ver_file = go_root / "VERSION"
    if ver_file.is_file():
        try:
            version = ver_file.read_text(errors="replace").strip().splitlines()[0].strip()
        except OSError:
            version = ""
    if not version:
        go_bin = go_root / "bin" / "go"
        if go_bin.is_file():
            rc, out = _run_capture([str(go_bin), "version"], timeout=4)
            if rc == 0 and out:
                version = _first_line(out).replace("go version", "").strip().split(" ")[0]
    return {"name": go_root.name, "path": str(go_root), "version": version}


async def probe_go_envs() -> dict:
    """探测 Go 环境：版本 / go env 关键变量 / 多版本工具链 / GOPATH 工具 / 模块与构建缓存"""
    result = {
        "available": False, "version": "", "goroot": "", "gopath": "", "goproxy": "",
        "gomodcache": "", "gobin": "", "gocache": "", "goversion": "", "goos": "", "goarch": "",
        "versions": [], "tools": [], "caches": [],
    }

    rc, out = _run_capture(["go", "version"], timeout=5)
    if rc == 0 and out:
        result["available"] = True
        result["version"] = _first_line(out).replace("go version", "").strip().split(" ")[0]

    rc2, out2 = _run_capture(["go", "env", "-json"], timeout=10)
    if rc2 == 0 and out2:
        try:
            genv = json.loads(out2)
        except Exception:
            genv = {}
        for key in ("GOROOT", "GOPATH", "GOPROXY", "GOMODCACHE", "GOBIN", "GOCACHE", "GOVERSION", "GOOS", "GOARCH"):
            result[key.lower()] = genv.get(key, "") or ""

    result["goversion"] = result["goversion"] or result["version"]

    # 多版本工具链
    roots = [Path(os.path.expanduser(r)) for r in GO_SCAN_ROOTS]
    if result["goroot"]:
        roots.insert(0, Path(os.path.expanduser(result["goroot"])))
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = [c for c in sorted(root.iterdir()) if c.is_dir()]
        except (PermissionError, OSError):
            children = []
        # goenv / sdkman 的目录下全是版本目录；系统目录里只挑 go* 前缀
        all_versions_root = root.name in ("versions", "go")
        for child in [root] + children:
            if not (child / "bin" / "go").is_file():
                continue
            if not all_versions_root and child is not root and not GO_DIR_RE.match(child.name):
                continue
            try:
                key = str(child.resolve())
            except OSError:
                key = str(child)
            if key in seen:
                continue
            seen.add(key)
            info = _describe_go(child)
            info["is_goroot"] = key == str(Path(result["goroot"]).resolve()) if result["goroot"] else False
            result["versions"].append(info)
            if len(result["versions"]) >= 30:
                break
        if len(result["versions"]) >= 30:
            break

    # GOPATH/bin 下的工具（gopls / dlv / air 等）
    gopath = result["gopath"] or str(Path.home() / "go")
    bin_dir = Path(os.path.expanduser(gopath)) / "bin"
    if bin_dir.is_dir():
        try:
            for f in sorted(bin_dir.iterdir()):
                if f.is_file() and os.access(f, os.X_OK):
                    result["tools"].append({"name": f.name, "path": str(f)})
                if len(result["tools"]) >= 40:
                    break
        except (PermissionError, OSError):
            pass

    # 模块缓存 / 构建缓存
    for label, path in (
        ("模块缓存 (GOMODCACHE)", result["gomodcache"] or "~/go/pkg/mod"),
        ("构建缓存 (GOCACHE)", result["gocache"] or "~/.cache/go-build"),
    ):
        entry = _cache_entry(label, path)
        if entry:
            result["caches"].append(entry)

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


def _safe_exists(path) -> bool:
    """安全判断路径是否存在：权限不足/符号链接异常等一律视为不存在"""
    try:
        return os.stat(path, follow_symlinks=False if not follow else True) is not None
    except OSError:
        return False


def _safe_isdir(path) -> bool:
    """安全判断是否为目录，异常时返回 False"""
    try:
        return os.path.isdir(path)
    except OSError:
        return False


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
