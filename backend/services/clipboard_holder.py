"""X11 CLIPBOARD 持有者：设置剪贴板内容并响应 SelectionRequest，供 xdotool ctrl+shift+v 粘贴

用法: python clipboard_holder.py <文本> [超时秒数]
设置后保持运行处理 selection 请求，直到超时或 stdin 关闭。
"""

import sys
import time

from Xlib import X, Xatom, display
from Xlib.protocol import event


def main():
    text = sys.argv[1].encode("utf-8") if len(sys.argv) > 1 else b""
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

    d = display.Display()
    clip_atom = d.intern_atom("CLIPBOARD")
    w = d.screen().root.create_window(0, 0, 1, 1, 0, X.CopyFromParent, X.InputOutput, X.CopyFromParent)
    w.set_selection_owner(clip_atom, X.CurrentTime)
    d.sync()

    utf8_atom = d.intern_atom("UTF8_STRING")
    text_atom = d.intern_atom("TEXT")

    deadline = time.time() + timeout
    while time.time() < deadline:
        # 非阻塞检查待处理事件（含 SelectionRequest）
        while d.pending_events():
            try:
                ev = d.next_event()
            except Exception:
                continue
            if ev.type == X.SelectionRequest:
                try:
                    target = ev.target
                    prop = ev.property
                    if prop == X.NONE:
                        prop = 0
                    if target == Xatom.TARGETS:
                        atoms = [Xatom.TARGETS, utf8_atom, Xatom.STRING, text_atom]
                        ev.requestor.change_property(prop, Xatom.ATOM, 32, atoms)
                    elif target in (utf8_atom, Xatom.STRING, text_atom):
                        ev.requestor.change_property(prop, target, 8, text)
                    else:
                        continue
                    # 回发 SelectionNotify
                    notify = event.SelectionNotify(
                        time=ev.time,
                        requestor=ev.requestor,
                        selection=ev.selection,
                        target=target,
                        property=prop,
                    )
                    d.send_event(ev.requestor, notify)
                except Exception:
                    pass
                d.sync()
        time.sleep(0.05)

    d.close()


if __name__ == "__main__":
    main()
