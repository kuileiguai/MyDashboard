"""M4 PTY 会话管理器（核心）"""

import os
import pty
import fcntl
import struct
import termios
import asyncio
import time
import uuid
from collections import deque
from pathlib import Path
from config import PTY_SCROLLBACK_LINES, PTY_MAX_SESSIONS


class PtySession:
    def __init__(self, session_id: str, name: str, cwd: str, master_fd: int, pid: int):
        self.session_id = session_id
        self.name = name
        self.cwd = cwd
        self.master_fd = master_fd
        self.pid = pid
        self.scrollback = deque(maxlen=PTY_SCROLLBACK_LINES)
        self.last_output_at = time.time()
        self.subscribers: list = []  # WS 订阅者列表
        self._reader_task: asyncio.Task | None = None

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "name": self.name,
            "cwd": self.cwd,
            "status": "yellow" if (time.time() - self.last_output_at) < 2 else "green",
            "subscribers": len(self.subscribers),
        }


class PtyManager:
    def __init__(self):
        self.sessions: dict[str, PtySession] = {}

    def create(self, name: str = "terminal", cwd: str = "~", shell: str = "/bin/bash", init_cmd: str = "") -> str:
        if len(self.sessions) >= PTY_MAX_SESSIONS:
            raise RuntimeError(f"Max {PTY_MAX_SESSIONS} sessions reached")

        sid = uuid.uuid4().hex[:12]
        cwd = str(Path(cwd).expanduser().resolve())

        # Create PTY
        master_fd, slave_fd = pty.openpty()
        pid = os.fork()

        if pid == 0:
            # Child: set up the terminal and exec shell
            os.close(master_fd)
            os.setsid()
            # Set terminal as controlling terminal
            try:
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            except OSError:
                pass

            os.chdir(cwd)
            # Set environment
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"

            # Redirect stdio to slave
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            os.close(slave_fd)

            if init_cmd:
                # Run shell with init command
                os.execve(shell, [shell, "-c", init_cmd], env)
            else:
                os.execve(shell, [shell], env)
            os._exit(1)

        # Parent
        os.close(slave_fd)
        # Set master fd to non-blocking
        fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        session = PtySession(sid, name, cwd, master_fd, pid)
        self.sessions[sid] = session
        return sid

    def write(self, sid: str, data: str | bytes):
        session = self.sessions.get(sid)
        if not session:
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            os.write(session.master_fd, data)
        except OSError:
            pass

    def resize(self, sid: str, rows: int, cols: int):
        session = self.sessions.get(sid)
        if not session:
            return
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(session.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def rename(self, sid: str, name: str):
        session = self.sessions.get(sid)
        if session:
            session.name = name

    def kill(self, sid: str):
        session = self.sessions.pop(sid, None)
        if not session:
            return
        try:
            os.kill(session.pid, 15)  # SIGTERM
        except OSError:
            pass
        try:
            os.close(session.master_fd)
        except OSError:
            pass

    def list_sessions(self):
        return [s.to_dict() for s in self.sessions.values()]

    async def read_loop(self, sid: str):
        """后台任务：从 PTY master fd 读取数据并推送给所有 WS 订阅者"""
        session = self.sessions.get(sid)
        if not session:
            return

        loop = asyncio.get_event_loop()
        buffer = b""

        while sid in self.sessions:
            try:
                data = await loop.run_in_executor(None, lambda: os.read(session.master_fd, 65536))
                if data:
                    session.last_output_at = time.time()
                    session.scrollback.append(data)
                    # Push to subscribers
                    try:
                        decoded = data.decode("utf-8", errors="replace")
                    except Exception:
                        decoded = data.decode("latin-1", errors="replace")

                    dead = []
                    for ws in session.subscribers:
                        try:
                            await ws.send_text(decoded)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        session.subscribers.remove(ws)
                else:
                    break  # fd closed
            except BlockingIOError:
                await asyncio.sleep(0.05)
            except OSError:
                break

        # Cleanup if process died
        if sid in self.sessions:
            self.kill(sid)

    def subscribe(self, sid: str, ws):
        session = self.sessions.get(sid)
        if not session:
            return None
        session.subscribers.append(ws)
        # Send scrollback as replay
        replay = b"".join(session.scrollback).decode("utf-8", errors="replace")
        return replay


# 全局单例
pty_manager = PtyManager()
