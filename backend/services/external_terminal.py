"""外部终端窗口检测与控制服务

通过 wmctrl + /proc + xdotool 探测本机已打开的终端窗口，
获取 PID、工作目录、运行命令等信息，并支持聚焦和发送指令。
"""

import os
import re
import subprocess
from pathlib import Path


# 已知终端模拟器的窗口标题匹配模式
TERMINAL_PATTERNS = [
    "gnome-terminal", "xfce4-terminal", "konsole", "terminator",
    "tilix", "alacritty", "kitty", "wezterm", "xterm", "urxvt",
    "rxvt", "st-", "foot", "cool-retro-term", "qterminal",
    "lxterminal", "mate-terminal", "deepin-terminal", "io.elementary.terminal",
]


def list_terminal_windows() -> list[dict]:
    """列出所有已打开的终端窗口"""
    windows = []

    # 1. 通过 wmctrl 获取窗口列表
    try:
        proc = subprocess.run(
            ["wmctrl", "-l", "-x"],  # -x 显示窗口类名
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return _fallback_xdotool()

    for line in proc.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        win_id, desktop, win_class, host, title = parts

        # 2. 检查是否为终端窗口
        class_lower = win_class.lower()
        title_lower = title.lower()
        is_terminal = any(p in class_lower for p in TERMINAL_PATTERNS)
        if not is_terminal:
            # 也检查标题是否像终端（含路径、用户名@主机名等）
            is_terminal = _looks_like_terminal(title_lower, class_lower)

        if not is_terminal:
            continue

        # 3. 获取窗口 PID
        pid = _get_window_pid(win_id)
        if not pid:
            continue

        # 4. 从 /proc 获取进程详情
        proc_info = _get_proc_info(pid)

        windows.append({
            "id": win_id,
            "desktop": int(desktop) if desktop.isdigit() else -1,
            "class": win_class,
            "title": title,
            "pid": pid,
            "cwd": proc_info.get("cwd", ""),
            "cmdline": proc_info.get("cmdline", ""),
            "shell": proc_info.get("shell", ""),
            "children": proc_info.get("children", []),
            "host": host,
        })

    return windows


def _looks_like_terminal(title: str, wm_class: str) -> bool:
    """启发式判断是否像是终端窗口"""
    # 含路径模式
    if re.search(r'[/~]\w+', title):
        return True
    # 用户@主机模式
    if re.search(r'\w+@\w+', title):
        return True
    # 已知的终端标题后缀
    terminal_markers = ['terminal', 'shell', 'bash', 'zsh', 'fish', 'tmux', 'ssh ']
    for marker in terminal_markers:
        if marker in title or marker in wm_class:
            return True
    return False


def _get_window_pid(win_id: str) -> int | None:
    """通过 xdotool 获取窗口的 PID"""
    try:
        proc = subprocess.run(
            ["xdotool", "getwindowpid", win_id],
            capture_output=True, text=True, timeout=3,
        )
        pid_str = proc.stdout.strip()
        if pid_str.isdigit():
            return int(pid_str)
    except Exception:
        pass

    # 备选：通过 xprop
    try:
        proc = subprocess.run(
            ["xprop", "-id", win_id, "_NET_WM_PID"],
            capture_output=True, text=True, timeout=3,
        )
        m = re.search(r'=\s*(\d+)', proc.stdout)
        if m:
            return int(m.group(1))
    except Exception:
        pass

    return None


def _get_proc_info(pid: int) -> dict:
    """从 /proc 读取进程信息"""
    info = {"cwd": "", "cmdline": "", "shell": "", "children": []}
    try:
        info["cwd"] = os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        pass
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read().decode("utf-8", errors="replace")
            info["cmdline"] = raw.replace("\x00", " ").strip()
    except Exception:
        pass
    try:
        with open(f"/proc/{pid}/comm") as f:
            info["shell"] = f.read().strip()
    except Exception:
        pass

    # 获取子进程（终端里正在跑的命令）
    try:
        for tid in os.listdir(f"/proc/{pid}/task"):
            children_path = f"/proc/{pid}/task/{tid}/children"
            if os.path.exists(children_path):
                with open(children_path) as f:
                    child_pids = f.read().strip().split()
                    for cpid in child_pids[:5]:  # 最多取 5 个
                        try:
                            with open(f"/proc/{cpid}/cmdline", "rb") as cf:
                                child_cmd = cf.read().decode("utf-8", errors="replace").replace("\x00", " ").strip()
                            with open(f"/proc/{cpid}/comm") as cf:
                                child_name = cf.read().strip()
                            info["children"].append({
                                "pid": int(cpid),
                                "name": child_name,
                                "cmdline": child_cmd[:200],
                            })
                        except Exception:
                            pass
                break  # 只取第一个 task
    except Exception:
        pass

    return info


def focus_window(win_id: str) -> bool:
    """聚焦终端窗口"""
    try:
        subprocess.run(["wmctrl", "-i", "-a", win_id], timeout=3)
        return True
    except Exception:
        return False


def close_window(win_id: str) -> bool:
    """关闭终端窗口"""
    try:
        subprocess.run(["wmctrl", "-i", "-c", win_id], timeout=3)
        return True
    except Exception:
        return False


def send_keys_to_window(win_id: str, text: str) -> bool:
    """向终端窗口发送按键/文本"""
    try:
        # type 分两种：普通文本用 "type"，特殊键用 "key"
        # 先聚焦
        subprocess.run(["xdotool", "windowactivate", win_id], timeout=2)
        # 发送文本
        subprocess.run(["xdotool", "type", "--window", win_id, text], timeout=3)
        return True
    except Exception:
        return False


def send_command_to_window(win_id: str, command: str) -> bool:
    """向终端窗口发送命令并回车"""
    try:
        subprocess.run(["xdotool", "windowactivate", win_id], timeout=2)
        subprocess.run(["xdotool", "type", "--window", win_id, command], timeout=3)
        subprocess.run(["xdotool", "key", "--window", win_id, "Return"], timeout=2)
        return True
    except Exception:
        return False


def send_command_to_active_window(command: str) -> bool:
    """向当前活动窗口发送命令并回车（小屏"点即执行"的落点）"""
    try:
        proc = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=3,
        )
        win_id = proc.stdout.strip()
        if not win_id:
            return False
        return send_command_to_window(win_id, command)
    except Exception:
        return False


def _fallback_xdotool() -> list[dict]:
    """wmctrl 不可用时的备选方案"""
    windows = []
    try:
        # 用 xdotool 搜索终端窗口
        for pattern in ["gnome-terminal", "Terminal", "terminal", "xterm", "konsole"]:
            try:
                proc = subprocess.run(
                    ["xdotool", "search", "--name", pattern],
                    capture_output=True, text=True, timeout=3,
                )
                for win_id in proc.stdout.strip().split("\n"):
                    win_id = win_id.strip()
                    if not win_id:
                        continue
                    pid = _get_window_pid(win_id)
                    if not pid:
                        continue
                    proc_info = _get_proc_info(pid)
                    # 获取标题
                    title = ""
                    try:
                        tp = subprocess.run(
                            ["xdotool", "getwindowname", win_id],
                            capture_output=True, text=True, timeout=2,
                        )
                        title = tp.stdout.strip()
                    except Exception:
                        pass
                    windows.append({
                        "id": win_id, "desktop": -1, "class": pattern,
                        "title": title, "pid": pid,
                        "cwd": proc_info.get("cwd", ""),
                        "cmdline": proc_info.get("cmdline", ""),
                        "shell": proc_info.get("shell", ""),
                        "children": proc_info.get("children", []),
                        "host": "",
                    })
            except Exception:
                continue
    except Exception:
        pass
    return windows
