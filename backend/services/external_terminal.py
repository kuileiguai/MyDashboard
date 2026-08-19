"""外部终端窗口检测与控制服务

通过 wmctrl + /proc + xdotool 探测本机已打开的终端窗口，
获取 PID、工作目录、运行命令等信息，并支持聚焦和发送指令。
"""

import os
import re
import subprocess
import time
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


def _get_geometry(win_id: str) -> dict:
    """获取窗口几何（X/Y/WIDTH/HEIGHT）"""
    try:
        proc = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", win_id],
            capture_output=True, text=True, timeout=3,
        )
        geo = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                geo[k] = v.strip()
        return geo
    except Exception:
        return {}


def _activate(win_id: str) -> bool:
    """激活窗口并确保 X 输入焦点落到该窗口（发送命令前调用）"""
    try:
        subprocess.run(["xdotool", "windowactivate", "--sync", win_id], timeout=3)
        # GNOME/mutter 下 windowfocus 常被 WM 焦点管理覆盖，需点击窗口标题栏让 WM 授予输入焦点
        # 注意：mousemove/click 不能用 --sync（远程桌面下会卡住等待 X 事件）
        geo = _get_geometry(win_id)
        cx = int(geo.get("X", 0) or 0) + int(geo.get("WIDTH", 800) or 800) // 2
        cy = int(geo.get("Y", 0) or 0) + 15  # 标题栏区域
        subprocess.run(["xdotool", "mousemove", str(cx), str(cy)], timeout=2)
        subprocess.run(["xdotool", "click", "1"], timeout=2)
        subprocess.run(["xdotool", "windowfocus", "--sync", win_id], timeout=2)
        # 轮询等待输入焦点落到目标窗口（mutter 焦点切换是异步的）
        target_dec = str(int(win_id, 16)) if win_id.lower().startswith("0x") else str(int(win_id))
        for _ in range(10):
            cur = subprocess.run(
                ["xdotool", "getwindowfocus"], capture_output=True, text=True, timeout=2,
            ).stdout.strip()
            if cur == target_dec:
                return True
            time.sleep(0.2)
        return False
    except Exception:
        return False


def send_keys_to_window(win_id: str, text: str) -> bool:
    """向终端窗口发送按键/文本（XTEST 真实按键，GTK 终端可靠；
    不用 --window，因为 XSendEvent 合成事件会被 GTK 应用忽略）"""
    try:
        if not _activate(win_id):
            return False
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "20", text], timeout=8)
        return True
    except Exception:
        return False


def send_command_to_window(win_id: str, command: str, press_enter: bool = True) -> bool:
    """向终端窗口发送命令（XTEST 真实按键 + --clearmodifiers）。
    press_enter=False 时只输入不回车（小屏点击场景，由用户自行确认执行）。"""
    try:
        if not _activate(win_id):
            return False
        subprocess.run(["xdotool", "type", "--clearmodifiers", "--delay", "20", command], timeout=8)
        if press_enter:
            subprocess.run(["xdotool", "key", "--clearmodifiers", "Return"], timeout=2)
        return True
    except Exception:
        return False


def _get_window_title(win_id: str) -> str:
    """获取窗口标题"""
    try:
        proc = subprocess.run(
            ["xdotool", "getwindowname", win_id],
            capture_output=True, text=True, timeout=3,
        )
        return proc.stdout.strip()
    except Exception:
        return ""


# 明显非终端的窗口标记（排除误判，如编辑器/浏览器标题含路径或 @）
_NON_TERMINAL_MARKERS = [
    "gedit", "libreoffice", "visual studio code", " - code", "sublime", "pycharm",
    "intellij", "idea", "webstorm", "eclipse", "vim -", "emacs", "firefox",
    "chromium", "chrome", "msedge", "edge", "reasonix", "dbeaver", "explorer",
]


def _window_is_terminal(win_id: str) -> bool:
    """判断指定窗口是否为终端窗口"""
    title = _get_window_title(win_id).lower()
    if not title:
        return False
    for m in _NON_TERMINAL_MARKERS:
        if m in title:
            return False
    return _looks_like_terminal(title, "")


def _get_stacking_windows() -> list[str]:
    """按 X 堆栈顺序（自底向上）返回所有窗口 id 列表，用于找"最近活动"窗口"""
    try:
        proc = subprocess.run(
            ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"],
            capture_output=True, text=True, timeout=3,
        )
        # 输出形如: _NET_CLIENT_LIST_STACKING(WINDOW): window id # 0x1000003, 0x2000005, ...
        m = re.search(r"window id # (.*)", proc.stdout)
        if m:
            return [x.strip() for x in m.group(1).split(",") if x.strip()]
    except Exception:
        pass
    return []


def send_command_to_active_window(command: str, press_enter: bool = True) -> bool:
    """发送命令到最近活动的终端窗口（小屏"点即执行"）。
    1) 当前活动窗口是终端 → 直接发送；
    2) 否则从 X 窗口堆栈顶部向下找最近活动的终端窗口发送。"""
    try:
        proc = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=3,
        )
        win_id = proc.stdout.strip()
        if win_id and _window_is_terminal(win_id):
            return send_command_to_window(win_id, command, press_enter)
        # 活动窗口不是终端（如浏览器/编辑器）：从堆栈顶部向下找最近活动的终端
        for wid in reversed(_get_stacking_windows()):
            if _window_is_terminal(wid):
                return send_command_to_window(wid, command, press_enter)
    except Exception:
        pass
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
