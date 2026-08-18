"""M5 监控 WebSocket 推送"""

import json
from fastapi import WebSocket, WebSocketDisconnect
from services.monitor_service import add_monitor_subscriber, remove_monitor_subscriber


async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    add_monitor_subscriber(websocket)
    try:
        while True:
            # 等待任意数据——用于保持连接（心跳）
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        remove_monitor_subscriber(websocket)
