"""Docker 管理服务：基于 docker CLI（--format json），无额外 Python 依赖

所有命令通过 subprocess 调用 docker，权限不足/daemon 不可用时返回友好错误。
"""

import json
import os
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


# ── Compose ──

def list_compose_projects(base: str = "") -> list[dict]:
    base = base or os.environ.get("DASH_COMPOSE_BASE", str(Path.home()))
    root = Path(base)
    projects = []
    if not root.is_dir():
        return projects
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        compose = d / "docker-compose.yml"
        if not compose.exists():
            compose = d / "compose.yml"
        if compose.exists():
            projects.append({"name": d.name, "path": str(d), "compose_file": str(compose)})
    return projects


def compose_action(project_dir: str, action: str) -> dict:
    """action: up/down/restart/ps/config"""
    compose = Path(project_dir) / "docker-compose.yml"
    if not compose.exists():
        compose = Path(project_dir) / "compose.yml"
    if not compose.exists():
        return {"ok": False, "output": "未找到 docker-compose.yml"}
    # 优先 docker compose (v2)，回退 docker-compose (v1)
    bin_name = "docker"
    base = ["docker", "compose", "-f", str(compose)]
    rc, out, err = _run(base + ["version"], timeout=5)
    if rc != 0:
        bin_name = "docker-compose"
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
