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
_user_hidden = False  # 用户手动隐藏后 follow 不再自动显示
_pinned = False  # 固定：窗口停住不跟随吸附
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


def _title_is_terminal(title: str) -> bool:
    """根据窗口标题启发式判断是否为终端"""
    t = title.lower()
    if re.search(r"[/~]\w+", t) or re.search(r"\w+@\w+", t):
        return True
    return any(m in t for m in _TERMINAL_MARKERS)


def is_terminal_window(win_id):
    """判断指定窗口是否为终端"""
    title = _run(["xdotool", "getwindowname", win_id])
    return _title_is_terminal(title)


def has_terminal_window() -> bool:
    """桌面上是否存在终端窗口（遍历 wmctrl 窗口列表）"""
    out = _run(["wmctrl", "-l"])
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 5 and _title_is_terminal(parts[4]):
            return True
    return False


def _window_is_iconic() -> bool:
    """检测悬浮窗当前是否处于最小化（Iconic）状态"""
    try:
        xid = get_window_xid()
        if not xid:
            return False
        out = _run(["xprop", "-id", str(xid), "WM_STATE"])
        return "Iconic" in out
    except Exception:
        return False


class Api:
    """暴露给前端的桥接：window.pywebview.api"""

    def _show(self):
        """恢复显示：最小化(iconify)窗口必须 deiconify，pywebview 的 show() 不会恢复最小化窗口"""
        if _WINDOW:
            _WINDOW.restore()
            _WINDOW.show()

    def hide(self):
        global _user_hidden
        _user_hidden = True
        if _WINDOW:
            _WINDOW.hide()

    def show(self):
        global _user_hidden
        _user_hidden = False
        self._show()

    def toggle(self):
        global _user_hidden
        if _WINDOW is None:
            return
        if _window_is_iconic():
            # 最小化中 → 直接恢复（一次唤回）
            _user_hidden = False
            self._show()
            return
        # 注意：pywebview 的 _WINDOW.hidden 不随 show/hide 更新，须用自维护的 _user_hidden 判断
        if _user_hidden:
            _user_hidden = False
            self._show()
        else:
            _user_hidden = True
            _WINDOW.hide()

    def minimize(self):
        if _WINDOW:
            _WINDOW.minimize()

    def togglePin(self):
        global _pinned
        _pinned = not _pinned
        return _pinned

    def isPinned(self):
        return _pinned


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


def _screen_size():
    """返回 (宽, 高)，失败时回退 1920x1080"""
    try:
        dg = _run(["xdotool", "getdisplaygeometry"]).split()
        if len(dg) == 2 and dg[0].isdigit() and dg[1].isdigit():
            return int(dg[0]), int(dg[1])
    except Exception:
        pass
    return int(os.environ.get("PALETTE_SCREEN_W", "1920")), int(os.environ.get("PALETTE_SCREEN_H", "1080"))


def _place_window(target):
    """把窗口移动到目标位置（去重），返回是否执行了移动"""
    global _last_pos
    if target == _last_pos:
        return False
    xid = get_window_xid()
    if xid:
        _run(["xdotool", "windowmove", str(xid), str(target[0]), str(target[1])])
    else:
        _WINDOW.move(*target)
    _last_pos = target
    return True


def _window_is_self(wid) -> bool:
    """活动窗口是否为悬浮窗自身（用户正在操作小屏时不应移动窗口）"""
    if not wid:
        return False
    try:
        xid = get_window_xid()
        if not xid:
            return False
        return str(xid) == str(wid) or (wid.lower().startswith("0x") and str(int(wid, 16)) == str(xid))
    except Exception:
        return False


def follow_loop():
    """后台线程：桌面上有终端窗口时显示（活动终端吸附/其他窗口移角落），无终端窗口时自动隐藏。
    手动隐藏用快捷键/托盘（_user_hidden）。"""
    global _WINDOW, _last_pos
    debug = os.environ.get("PALETTE_DEBUG", "") == "1"
    while True:
        try:
            if _WINDOW is None or _pause_follow:
                time.sleep(POLL_INTERVAL)
                continue

            # 用户正在操作小屏（滚动列表/拖窗口）时：不移动、不隐藏、不吸附
            if _window_is_self(get_active_window_id()):
                time.sleep(POLL_INTERVAL)
                continue

            if _pinned:
                # 固定：窗口停住，不跟随吸附、无终端也不自动隐藏（用户手动隐藏仍优先）
                if not _user_hidden and _WINDOW.hidden:
                    _WINDOW.show()
                    _last_pos = None
                time.sleep(POLL_INTERVAL)
                continue

            # 桌面上没有任何终端窗口 → 自动隐藏
            if not has_terminal_window():
                if not _WINDOW.hidden:
                    _WINDOW.hide()
                if debug:
                    print("[follow] 无终端窗口，自动隐藏", flush=True)
                time.sleep(POLL_INTERVAL)
                continue

            sw, sh = _screen_size()
            wid = get_active_window_id()
            if wid and is_terminal_window(wid):
                geo = get_window_geometry(wid)
                x = int(geo.get("X", 0) or 0)
                y = int(geo.get("Y", 0) or 0)
                w = int(geo.get("WIDTH", 800) or 800)
                # 屏幕边界：右侧放不下则放终端左侧，仍放不下则贴屏幕右缘
                target_x = x + w + GAP
                if target_x + WIN_W > sw:
                    target_x = x - GAP - WIN_W
                    if target_x < 0:
                        target_x = max(0, sw - WIN_W)
                target = (target_x, y)
            else:
                # 有终端但活动窗口非终端：移到屏幕右下角（留出边距），保持可见
                target = (max(0, sw - WIN_W - GAP), max(0, sh - WIN_H - GAP))
            if _user_hidden:
                time.sleep(POLL_INTERVAL)
                continue
            if _WINDOW.hidden:
                _WINDOW.show()
                _last_pos = None  # 重新显示后强制下次重新定位
            _place_window(target)
            if debug:
                print(f"[follow] -> {target}（活动窗口 {wid or '<none>'}）", flush=True)
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
    # 禁用全局 easy_drag（否则内容区/滚动条按住拖动会移动整个窗口），
    # 改用指定拖动区域：仅顶部 .drag-region 拖动条可移动窗口
    webview.settings['DRAG_REGION_SELECTOR'] = '.drag-region'
    webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY'] = True
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
        easy_drag=False,
        js_api=Api(),
    )

    threading.Thread(target=follow_loop, daemon=True).start()
    start_hotkey()
    start_tray()

    print(f"[quickpalette] 加载 {PALETTE_URL}（{WIN_W}x{WIN_H}）")
    # private_mode=False：隐私模式会禁用 localStorage，导致 App.vue 渲染报错白屏
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
