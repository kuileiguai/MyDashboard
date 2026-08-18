#!/usr/bin/env python3
"""悬浮小屏宿主（命令随手查）

- pywebview 无边框置顶窗口，加载工作台的 /quickpalette 页面
- 自动吸附当前活动终端窗口：切到终端时贴其右缘显示，切走则隐藏
- 全局快捷键切换显示（需 pynput，默认 Ctrl+Shift+Space）
- 系统托盘图标（需 pystray + Pillow）

依赖均为可选：缺失时自动降级，不影响核心悬浮窗功能。
用法：先启动后端（uvicorn），再运行本脚本。
"""

import os
import re
import subprocess
import threading
import time

# ── WebKitGTK 渲染优化（必须在 import webview 之前设置）──
# 无 GPU/远程桌面下 GL 初始化失败会导致 WebKitWebProcess 空转吃满 CPU：
#   · 禁用 DMABUF 渲染器，回退到共享内存渲染
#   · 强制 Mesa 软件 GL（llvmpipe），避免 GL 初始化反复失败重试
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

import webview

DASH_URL = os.environ.get("DASH_URL", "http://127.0.0.1:8787")
PALETTE_URL = DASH_URL.rstrip("/") + "/quickpalette"
WIN_W = int(os.environ.get("PALETTE_WIDTH", "460"))
WIN_H = int(os.environ.get("PALETTE_HEIGHT", "380"))
GAP = int(os.environ.get("PALETTE_GAP", "12"))
POLL_INTERVAL = float(os.environ.get("PALETTE_POLL", "1.5"))
HOTKEY = os.environ.get("PALETTE_HOTKEY", "<ctrl>+<shift>+<space>")

_WINDOW = None
_pause_follow = False
_seen_terminal = False  # 是否已吸附过一次终端（之后才启用"切走隐藏"）
_last_pos = None  # 上次定位，避免重复 move


def _run(cmd, timeout=3):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def get_active_window_id():
    return _run(["xdotool", "getactivewindow"])


def get_window_geometry(win_id):
    out = _run(["xdotool", "getwindowgeometry", "--shell", win_id])
    geo = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            geo[k] = v.strip()
    return geo


_TERMINAL_MARKERS = [
    "terminal", "shell", "bash", "zsh", "fish", "tmux", "ssh", "konsole", "xterm",
    "tilix", "alacritty", "kitty", "wezterm", "gnome-terminal", "st-",
    "cool-retro-term", "qterminal", "lxterminal", "mate-terminal", "deepin-terminal",
]


def is_terminal_window(win_id):
    """启发式判断活动窗口是否为终端"""
    title = _run(["xdotool", "getwindowname", win_id]).lower()
    if re.search(r"[/~]\w+", title) or re.search(r"\w+@\w+", title):
        return True
    return any(m in title for m in _TERMINAL_MARKERS)


class Api:
    """暴露给前端的桥接：window.pywebview.api"""

    def hide(self):
        if _WINDOW:
            _WINDOW.hide()

    def show(self):
        if _WINDOW:
            _WINDOW.show()

    def toggle(self):
        if _WINDOW:
            _WINDOW.show() if _WINDOW.hidden else _WINDOW.hide()


def toggle_window():
    global _pause_follow
    if _WINDOW is None:
        return
    _pause_follow = True
    try:
        Api().toggle()
    finally:
        threading.Timer(1.0, _clear_pause).start()


def _clear_pause():
    global _pause_follow
    _pause_follow = False


def get_window_xid():
    """获取 pywebview 窗口的 X11 window id"""
    global _WINDOW
    if _WINDOW is None:
        return None
    try:
        from webview.platforms import gtk as _gtk
        bv = _gtk.BrowserView.instances.get(_WINDOW.uid)
        gdk_win = bv.window.get_window() if bv else None
        return gdk_win.get_xid() if gdk_win else None
    except Exception:
        return None


def follow_loop():
    """后台线程：跟随活动终端定位；启动后先吸附过一次终端，切走才隐藏"""
    global _WINDOW, _seen_terminal, _last_pos
    debug = os.environ.get("PALETTE_DEBUG", "") == "1"
    while True:
        try:
            if _WINDOW is None or _pause_follow:
                time.sleep(POLL_INTERVAL)
                continue
            wid = get_active_window_id()
            if wid and is_terminal_window(wid):
                _seen_terminal = True
                geo = get_window_geometry(wid)
                x = int(geo.get("X", 0) or 0)
                y = int(geo.get("Y", 0) or 0)
                w = int(geo.get("WIDTH", 800) or 800)
                # 屏幕边界：右侧放不下则放终端左侧，仍放不下则贴屏幕右缘
                sw = int(os.environ.get("PALETTE_SCREEN_W", "1920"))
                try:
                    dg = _run(["xdotool", "getdisplaygeometry"]).split()
                    if len(dg) == 2 and dg[0].isdigit():
                        sw = int(dg[0])
                except Exception:
                    pass
                target_x = x + w + GAP
                if target_x + WIN_W > sw:
                    target_x = x - GAP - WIN_W
                    if target_x < 0:
                        target_x = max(0, sw - WIN_W)
                target = (target_x, y)
                if target != _last_pos:
                    xid = get_window_xid()
                    if xid:
                        _run(["xdotool", "windowmove", str(xid), str(target[0]), str(target[1])])
                    else:
                        _WINDOW.move(*target)
                    _last_pos = target
                if _WINDOW.hidden:
                    _WINDOW.show()
                    _last_pos = None  # 重新显示后强制下次重新定位
                if debug:
                    print(f"[follow] 终端 {wid} -> {target}", flush=True)
            else:
                # 启动初期保持可见，让用户知道小屏已就绪；吸附过终端后才自动隐藏
                if _seen_terminal and not _WINDOW.hidden:
                    _WINDOW.hide()
                if debug:
                    print(f"[follow] 非终端窗口 {wid or '<none>'}（{'隐藏' if _seen_terminal else '保持可见'}）", flush=True)
        except Exception as e:
            if debug:
                print(f"[follow] error: {e}", flush=True)
        time.sleep(POLL_INTERVAL)


def start_hotkey():
    try:
        from pynput import keyboard
    except Exception:
        print(f"[quickpalette] pynput 未安装，跳过全局快捷键（{HOTKEY}）")
        return
    try:
        hotkey = keyboard.GlobalHotKeys({HOTKEY: toggle_window})
        hotkey.start()
        print(f"[quickpalette] 全局快捷键已注册：{HOTKEY}")
    except Exception as e:
        print(f"[quickpalette] 快捷键注册失败：{e}")


def start_tray():
    # GNOME 下 appindicator typelib 常缺失，强制 GTK 后端避免 import 崩溃
    os.environ.setdefault("PYSTRAY_BACKEND", "gtk")
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception as e:
        print(f"[quickpalette] 托盘不可用（{e}）")
        return

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([6, 6, 58, 58], fill=(64, 158, 255, 255))
    d.text((16, 20), ">_", fill="white")

    def _quit(icon, item):
        icon.stop()
        if _WINDOW:
            _WINDOW.destroy()

    menu = pystray.Menu(
        pystray.MenuItem("显示/隐藏", lambda icon, item: toggle_window(), default=True),
        pystray.MenuItem("退出", _quit),
    )
    icon = pystray.Icon("quickpalette", img, "命令小屏", menu)
    icon.run_detached()
    print("[quickpalette] 托盘图标已启动")


def main():
    global _WINDOW
    _WINDOW = webview.create_window(
        "命令小屏",
        PALETTE_URL,
        width=WIN_W,
        height=WIN_H,
        x=100,
        y=100,
        frameless=True,
        on_top=True,
        resizable=True,
        focus=True,
        js_api=Api(),
    )

    threading.Thread(target=follow_loop, daemon=True).start()
    start_hotkey()
    start_tray()

    print(f"[quickpalette] 加载 {PALETTE_URL}（{WIN_W}x{WIN_H}）")
    webview.start()


if __name__ == "__main__":
    main()
