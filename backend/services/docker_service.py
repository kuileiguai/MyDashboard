"""Docker 管理服务：基于 docker CLI（--format json），无额外 Python 依赖

所有命令通过 subprocess 调用 docker，权限不足/daemon 不可用时返回友好错误。
"""

import json
import os
import re
import subprocess
from pathlib import Path


def _run(cmd, timeout=10):
    """执行命令，返回 (returncode, stdout, stderr)"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return -1, "", "docker 命令未找到"
    except subprocess.TimeoutExpired:
        return -1, "", "命令执行超时"


def _json_rows(out: str) -> list[dict]:
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows


def docker_available() -> dict:
    rc, out, err = _run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=8)
    if rc == 0:
        return {"available": True, "version": out.strip()}
    err_text = (err or out).strip()
    hint = ""
    if "permission denied" in err_text:
        hint = ("当前用户无 docker.sock 访问权限。解决办法：\n"
                "1) sudo usermod -aG docker $USER   （把当前用户加入 docker 组，然后重新登录）\n"
                "2) 若仍不行：sudo chown root:docker /var/run/docker.sock")
    return {"available": False, "error": err_text, "hint": hint}


# ── 容器 ──

def list_containers(all_containers: bool = False) -> list[dict]:
    cmd = ["docker", "ps", "-a" if all_containers else "", "--format", "{{json .}}"]
    cmd = [c for c in cmd if c]
    rc, out, err = _run(cmd, timeout=10)
    if rc != 0:
        return [{"error": (err or out).strip()}]
    return _json_rows(out)


def container_action(cid: str, action: str) -> dict:
    """action: start/stop/restart/pause/unpause/kill/rm"""
    if action == "rm":
        cmd = ["docker", "rm", "-f", cid]
    else:
        cmd = ["docker", action, cid]
    rc, out, err = _run(cmd, timeout=20)
    return {"ok": rc == 0, "output": (out or err).strip()}


def container_logs(cid: str, tail: int = 200) -> str:
    rc, out, err = _run(["docker", "logs", "--tail", str(tail), cid], timeout=10)
    return out or err


def container_inspect(cid: str) -> dict:
    rc, out, err = _run(["docker", "inspect", cid], timeout=10)
    if rc != 0:
        return {"error": (err or out).strip()}
    try:
        data = json.loads(out)
        return data[0] if data else {}
    except Exception:
        return {"raw": out}


def container_stats() -> list[dict]:
    rc, out, err = _run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], timeout=15)
    if rc != 0:
        return [{"error": (err or out).strip()}]
    return _json_rows(out)


# ── 镜像 ──

def list_images() -> list[dict]:
    rc, out, err = _run(["docker", "images", "--format", "{{json .}}"], timeout=10)
    if rc != 0:
        return [{"error": (err or out).strip()}]
    return _json_rows(out)


def image_action(iid: str, action: str) -> dict:
    """action: rmi / prune"""
    if action == "prune":
        cmd = ["docker", "image", "prune", "-f"]
    else:
        cmd = ["docker", "rmi", "-f", iid]
    rc, out, err = _run(cmd, timeout=30)
    return {"ok": rc == 0, "output": (out or err).strip()}


def pull_image(name: str, tag: str = "latest") -> dict:
    rc, out, err = _run(["docker", "pull", f"{name}:{tag}"], timeout=180)
    return {"ok": rc == 0, "output": (out or err).strip()}


def default_save_dir() -> str:
    """镜像导出默认目录，可通过 DASH_IMAGE_SAVE_DIR 覆盖"""
    return os.environ.get("DASH_IMAGE_SAVE_DIR", "").strip() or str(Path.home() / "docker-images")


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{num} B"


def _safe_filename(name: str) -> str:
    """去掉目录成分与非法字符，防止路径穿越"""
    name = Path(name or "").name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-")
    return name or "image.tar"


def save_image(images: list[str], output_dir: str = "", filename: str = "",
               compress: bool = False, timeout: int = 1800) -> dict:
    """docker save 导出镜像到指定目录的文件（tar / tar.gz）"""
    images = [i.strip() for i in (images or []) if i.strip()]
    if not images:
        return {"ok": False, "output": "请先选择要保存的镜像"}

    out_dir = Path(output_dir or default_save_dir()).expanduser()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_dir = out_dir.resolve()
    except Exception as e:
        return {"ok": False, "output": f"目录不可用：{e}"}
    if not out_dir.is_dir():
        return {"ok": False, "output": f"{out_dir} 不是目录"}
    if not os.access(out_dir, os.W_OK):
        return {"ok": False, "output": f"目录不可写：{out_dir}"}

    filename = filename.strip()
    if filename:
        compress = compress or filename.lower().endswith((".gz", ".tgz"))
    else:
        base = _safe_filename(images[0].replace(":", "_").replace("/", "_"))
        filename = f"{base}.tar.gz" if compress else f"{base}.tar"
    filename = _safe_filename(filename)
    if compress and not filename.lower().endswith((".gz", ".tgz")):
        filename += ".gz"

    target = out_dir / filename
    if target.exists() and target.is_dir():
        return {"ok": False, "output": f"目标已存在且为目录：{target}"}

    try:
        if compress:
            rc, err = 0, ""
            with open(target, "wb") as f:
                p1 = subprocess.Popen(["docker", "save", *images],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                p2 = subprocess.Popen(["gzip", "-c"], stdin=p1.stdout, stdout=f)
                p1.stdout.close()  # 让 p1 收到 SIGPIPE
                _, err1 = p1.communicate(timeout=timeout)
                p2.wait(timeout=timeout)
                if p1.returncode != 0 or p2.returncode != 0:
                    rc = 1
                err = (err1 or b"").decode(errors="replace")
        else:
            rc, _, err = _run(["docker", "save", "-o", str(target), *images], timeout=timeout)
    except FileNotFoundError:
        return {"ok": False, "output": "docker 命令未找到"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "保存超时，请改用更小的镜像或延长超时"}

    if rc != 0:
        try:
            target.unlink(missing_ok=True)  # 清理残缺文件
        except Exception:
            pass
        return {"ok": False, "output": (err or "").strip() or "docker save 执行失败"}

    size = target.stat().st_size
    return {"ok": True, "path": str(target), "size": size, "size_human": _human_size(size)}


# ── Compose ──

COMPOSE_FILE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def find_compose_file(project_dir) -> Path | None:
    """在项目目录下查找 compose 文件，找不到返回 None"""
    d = Path(str(project_dir)).expanduser()
    for name in COMPOSE_FILE_NAMES:
        f = d / name
        try:
            if f.is_file():
                return f
        except OSError:
            continue
    return None


def list_compose_projects(base: str = "") -> list[dict]:
    base = base or os.environ.get("DASH_COMPOSE_BASE", str(Path.home()))
    root = Path(str(base)).expanduser()
    projects = []
    if not root.is_dir():
        return projects
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        compose = find_compose_file(d)
        if compose:
            projects.append({"name": d.name, "path": str(d), "compose_file": str(compose)})
    return projects


def verify_compose_projects(projects: list[dict]) -> list[dict]:
    """复核记录中的 compose 是否仍然存在"""
    result = []
    for p in projects:
        item = dict(p)
        path = str(item.get("path") or "")
        d = Path(path).expanduser() if path else None
        compose = find_compose_file(d) if d else None
        item["dir_exists"] = bool(d and d.is_dir())
        item["exists"] = bool(compose)
        if compose:
            item["compose_file"] = str(compose)
        result.append(item)
    return result


def read_compose_file(path: str, max_bytes: int = 2 * 1024 * 1024) -> dict:
    """读取 compose 文件内容（仅允许 compose 文件名）"""
    p = Path(str(path)).expanduser()
    if p.name not in COMPOSE_FILE_NAMES:
        return {"ok": False, "error": f"仅支持编辑 {'/'.join(COMPOSE_FILE_NAMES)}"}
    try:
        p = p.resolve()
    except OSError as e:
        return {"ok": False, "error": str(e)}
    if not p.is_file():
        return {"ok": False, "error": "文件不存在"}
    size = p.stat().st_size
    if size > max_bytes:
        return {"ok": False, "error": f"文件过大（{_human_size(size)}），请用编辑器打开"}
    return {"ok": True, "path": str(p), "content": p.read_text(encoding="utf-8", errors="replace"),
            "size": size, "mtime": p.stat().st_mtime}


def write_compose_file(path: str, content: str) -> dict:
    """写回 compose 文件内容"""
    p = Path(str(path)).expanduser()
    if p.name not in COMPOSE_FILE_NAMES:
        return {"ok": False, "error": f"仅支持编辑 {'/'.join(COMPOSE_FILE_NAMES)}"}
    try:
        p = p.resolve()
    except OSError as e:
        return {"ok": False, "error": str(e)}
    if not p.parent.is_dir():
        return {"ok": False, "error": f"目录不存在：{p.parent}"}
    try:
        if p.exists():
            p.replace(p.with_suffix(p.suffix + ".bak"))  # 保留上一版，便于回滚
        p.write_text(content, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    size = p.stat().st_size
    return {"ok": True, "path": str(p), "size": size, "size_human": _human_size(size)}


def compose_action(project_dir: str, action: str) -> dict:
    """action: up/down/restart/ps/config"""
    compose = find_compose_file(project_dir)
    if not compose:
        return {"ok": False, "output": "未找到 compose 文件（docker-compose.yml / compose.yml）"}
    # 优先 docker compose (v2)，回退 docker-compose (v1)
    base = ["docker", "compose", "-f", str(compose)]
    rc, out, err = _run(base + ["version"], timeout=5)
    if rc != 0:
        base = ["docker-compose", "-f", str(compose)]
    if action == "up":
        base += ["up", "-d"]
    elif action == "ps":
        base += ["ps"]
    elif action == "config":
        base += ["config"]
    else:
        base += [action]
    rc, out, err = _run(base, timeout=60)
    return {"ok": rc == 0, "output": (out or err).strip()}


# ── 卷 ──

def list_volumes() -> list[dict]:
    rc, out, err = _run(["docker", "volume", "ls", "--format", "{{json .}}"], timeout=10)
    if rc != 0:
        return [{"error": (err or out).strip()}]
    return _json_rows(out)


def volume_action(name: str, action: str) -> dict:
    """action: create/rm"""
    if action == "create":
        cmd = ["docker", "volume", "create", name]
    else:
        cmd = ["docker", "volume", "rm", name]
    rc, out, err = _run(cmd, timeout=15)
    return {"ok": rc == 0, "output": (out or err).strip()}


# ── 网络 ──

def list_networks() -> list[dict]:
    rc, out, err = _run(["docker", "network", "ls", "--format", "{{json .}}"], timeout=10)
    if rc != 0:
        return [{"error": (err or out).strip()}]
    return _json_rows(out)


def network_action(name: str, action: str, driver: str = "bridge") -> dict:
    """action: create/rm"""
    if action == "create":
        cmd = ["docker", "network", "create", "-d", driver, name]
    else:
        cmd = ["docker", "network", "rm", name]
    rc, out, err = _run(cmd, timeout=15)
    return {"ok": rc == 0, "output": (out or err).strip()}


# ── 系统级 ──

def system_info() -> dict:
    rc, out, err = _run(["docker", "info", "--format",
                         "{{.ServerVersion}}|{{.Containers}}|{{.Images}}|{{.Name}}"], timeout=8)
    if rc != 0:
        return {"available": False, "error": (err or out).strip()}
    parts = out.strip().split("|")
    return {
        "available": True,
        "version": parts[0] if len(parts) > 0 else "",
        "containers": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
        "images": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
        "name": parts[3] if len(parts) > 3 else "",
    }


def system_df() -> dict:
    rc, out, err = _run(["docker", "system", "df"], timeout=15)
    if rc != 0:
        return {"ok": False, "error": (err or out).strip()}
    return {"ok": True, "raw": out}


def system_prune() -> dict:
    rc, out, err = _run(["docker", "system", "prune", "-af"], timeout=60)
    return {"ok": rc == 0, "output": (out or err).strip()}
