"""M4-F11: tmux 会话集成"""

import subprocess
import os


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
