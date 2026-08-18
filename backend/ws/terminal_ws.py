"""M4 终端 WebSocket 桥接"""

import asyncio
import json
from fastapi import WebSocket, WebSocketDisconnect
from services.pty_manager import pty_manager


async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    # 订阅到 PTY 会话
    replay = pty_manager.subscribe(session_id, websocket)
    if replay is None:
        await websocket.send_text("Session not found. It may have been closed.")
        await websocket.close()
        return

    # 先回放 scrollback
    if replay:
        await websocket.send_text(replay)

    # 启动后台 reader（如果还没启动）
    session = pty_manager.sessions.get(session_id)
    if session and session._reader_task is None:
        session._reader_task = asyncio.create_task(pty_manager.read_loop(session_id))

    try:
        while True:
            data = await websocket.receive_text()
            # 支持 JSON 控制消息（resize 等）或纯文本数据
            if data.startswith('{"') or data.startswith('{'):
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "resize":
                        pty_manager.resize(session_id, msg.get("rows", 24), msg.get("cols", 80))
                    elif msg.get("type") == "input":
                        pty_manager.write(session_id, msg.get("data", ""))
                    continue
                except json.JSONDecodeError:
                    pass
            # 纯文本 = 直接写入 PTY
            pty_manager.write(session_id, data)
    except WebSocketDisconnect:
        pass
    finally:
        # 取消订阅，但不杀进程
        if session:
            if websocket in session.subscribers:
                session.subscribers.remove(websocket)
