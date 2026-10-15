"""M4-F11: tmux 会话集成"""

import os
import shutil
import subprocess
import time


def _env() -> dict:
    """清掉 TMUX 环境变量，避免在 tmux 内部调用时被嵌套限制"""
    return {**os.environ, "TMUX": ""}


def tmux_available() -> bool:
    """tmux 是否已安装并可执行"""
    return shutil.which("tmux") is not None


def list_tmux_sessions() -> list[dict]:
    """列出当前用户的 tmux 会话"""
    sessions = []
    try:
        proc = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}:#{session_windows}:#{session_created}"],
            capture_output=True, text=True, timeout=3,
            env={**os.environ, "TMUX": ""},
        )
        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(":", 2)
            if len(parts) >= 3:
                sessions.append({
                    "name": parts[0],
                    "windows": int(parts[1]) if parts[1].isdigit() else 0,
                    "created": parts[2],
                })
    except Exception:
        pass
    return sessions


def attach_tmux_session(name: str, read_only: bool = False) -> str:
    """返回可执行的 tmux attach 命令"""
    flags = "-r" if read_only else ""
    return f"tmux attach -t {name} {flags}".strip()


def tmux_info() -> dict:
    """tmux 服务端信息"""
    try:
        proc = subprocess.run(
            ["tmux", "info"],
            capture_output=True, text=True, timeout=3,
            env={**os.environ, "TMUX": ""},
        )
        return {"running": proc.returncode == 0, "info": proc.stdout[:500]}
    except Exception:
        return {"running": False, "error": "tmux not available"}


# ── 外部终端窗口接管 ──────────────────────────────────────────────

def session_name_for_window(pid: int) -> str:
    """按终端窗口 PID 生成稳定的 tmux 会话名（重复接管同一窗口会复用）"""
    return f"deckpit-w{pid}"


def has_session(name: str) -> bool:
    try:
        return subprocess.run(
            ["tmux", "has-session", "-t", name],
            capture_output=True, timeout=3, env=_env(),
        ).returncode == 0
    except Exception:
        return False


def wait_for_session(name: str, timeout: float = 8.0) -> bool:
    """等待被注入的终端把 tmux 会话建立起来"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if has_session(name):
            return True
        time.sleep(0.3)
    return False


def find_session_by_pane_pid(pid: int | None) -> str | None:
    """该 shell 是否已经在某个 tmux pane 里 —— 命中即可直接 attach，无需注入"""
    if not pid:
        return None
    try:
        proc = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}"],
            capture_output=True, text=True, timeout=3, env=_env(),
        )
        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) == 2 and parts[1].strip() == str(pid):
                return parts[0]
    except Exception:
        pass
    return None


def pane_pid_sessions() -> dict[int, str]:
    """一次性拿到 {pane_pid: session_name} 映射，避免逐个窗口反复调用 tmux"""
    mapping: dict[int, str] = {}
    try:
        proc = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", "#{session_name}\t#{pane_pid}"],
            capture_output=True, text=True, timeout=3, env=_env(),
        )
        for line in proc.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) == 2 and parts[1].strip().isdigit():
                mapping[int(parts[1].strip())] = parts[0]
    except Exception:
        pass
    return mapping
