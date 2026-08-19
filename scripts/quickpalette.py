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
# 替换原来的两行 setdefault
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

# 仅当没有硬件 GL 时才回退软件渲染（有 GPU 时保留硬件加速以支持透明）
try:
    import subprocess as _sp
    _gl_check = _sp.run(["glxinfo"], capture_output=True, text=True, timeout=3)
    _has_hw_gl = "direct rendering: Yes" in _gl_check.stdout.lower()
except Exception:
    _has_hw_gl = False

if not _has_hw_gl:
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    print("[quickpalette] 无硬件GL，已启用软件渲染（透明可能不可用）")

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


def _compositor_available():
    """探测桌面合成器（仅用于日志提示，不影响透明默认开启）：
    - Wayland 会话本身即合成渲染，直接判定可用
    - X11 下查询 _NET_WM_CM_S0 选择器是否有 owner
    - 探测失败按可用处理（不误伤正常桌面）"""
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return True
    try:
        out = _run(["xprop", "-root", "_NET_WM_CM_S0"], timeout=2)
        return bool(out.strip()) and "not found" not in out.lower()
    except Exception:
        return True


# 透明窗口（圆角面板四角透出桌面）：默认开启（画布透明）。
#   PALETTE_TRANSPARENT=0 显式关闭（改用微粉兜底）；=1 或未设置均开启。
#   合成器探测结果只写日志提示：无合成器环境下若显示异常，可设 0 回退。
# 替换原来的 TRANSPARENT 赋值逻辑
_transparent_env = os.environ.get("PALETTE_TRANSPARENT")
if _transparent_env == "0":
    TRANSPARENT = False
    TRANSPARENT_REASON = "显式关闭（PALETTE_TRANSPARENT=0）"
elif _transparent_env == "1":
    TRANSPARENT = True
    TRANSPARENT_REASON = "显式开启（PALETTE_TRANSPARENT=1，若显示异常请设为0）"
else:
    # 未设置环境变量时：严格依赖合成器检测结果
    _comp = _compositor_available()
    TRANSPARENT = _comp  # ← 关键改动：无合成器则自动关闭透明
    TRANSPARENT_REASON = (
        "默认开启（已检测到合成器）" if _comp
        else "自动关闭（未检测到合成器，如需强制开启设 PALETTE_TRANSPARENT=1）"
    )


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

    def isTransparent(self):
        """是否启用透明窗口（前端据此决定 body 背景：透明透桌面 / 微粉兜底）"""
        return TRANSPARENT


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


def _ensure_loopback_no_proxy():
    """修复 WebKit 加载本机后端报 "Could not connect: Connection refused"。

    Clash 类本地代理（gsettings manual 127.0.0.1:7890）会拒绝转发回环请求。
    WebKit 的代理解析器（GProxyResolverGnome / libproxy）只认 ignore 列表里的
    精确 IP / 域名（GLib 不支持 '*' 通配符，libproxy 对 CIDR 127.0.0.0/8 支持不佳），
    且部分 Clash 版本设置系统代理时会清空 ignore-hosts，导致 127.0.0.1 被送去代理而报错。

    这里做两件事（幂等、只增不减，不影响其他代理配置）：
    1) 进程级 no_proxy 设为精确回环地址（libproxy 路径兜底）；
    2) 确保系统 gsettings ignore-hosts 包含 localhost / 127.0.0.1 / ::1。
    """
    os.environ["no_proxy"] = "127.0.0.1,localhost,::1,0.0.0.0"
    os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1,0.0.0.0"
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.system.proxy", "ignore-hosts"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        if out.startswith("["):
            items = [x.strip().strip("'\"") for x in out.strip("[]").split(",") if x.strip()]
            changed = False
            for add in ("localhost", "127.0.0.1", "::1"):
                if add not in items:
                    items.append(add)
                    changed = True
            if changed:
                new_val = "[" + ", ".join(f"'{i}'" for i in items) + "]"
                proc = subprocess.run(
                    ["gsettings", "set", "org.gnome.system.proxy", "ignore-hosts", new_val],
                    capture_output=True, text=True, timeout=5,
                )
                if proc.returncode == 0:
                    print(f"[quickpalette] 已把回环地址加入系统代理绕过列表: {new_val}", flush=True)
    except Exception:
        pass  # 无 D-Bus 会话/只读 dconf 时跳过，不影响悬浮小屏本身


def main():
    global _WINDOW
    _ensure_loopback_no_proxy()
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
        transparent=TRANSPARENT,
        resizable=True,
        focus=True,
        easy_drag=False,
        js_api=Api(),
    )

    threading.Thread(target=follow_loop, daemon=True).start()
    start_hotkey()
    start_tray()

    print(f"[quickpalette] 加载 {PALETTE_URL}（{WIN_W}x{WIN_H}）")
    print(f"[quickpalette] 透明窗口: {'开启' if TRANSPARENT else '关闭'}（{TRANSPARENT_REASON}）")
    # private_mode=False：隐私模式会禁用 localStorage，导致 App.vue 渲染报错白屏
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
