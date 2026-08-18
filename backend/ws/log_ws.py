"""M6 日志 tail WebSocket 推送"""

import os
import asyncio
from pathlib import Path
from fastapi import WebSocket, WebSocketDisconnect, Query
from routers.logs import notify_error_alert


async def websocket_endpoint(websocket: WebSocket, path: str = Query("")):
    await websocket.accept()

    p = Path(path).expanduser().resolve()
    if not p.exists():
        await websocket.send_json({"error": "File not found"})
        await websocket.close()
        return

    last_size = p.stat().st_size

    try:
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                if msg == "stop":
                    break
            except asyncio.TimeoutError:
                pass

            try:
                current_size = p.stat().st_size
                if current_size > last_size:
                    with open(p, "rb") as f:
                        f.seek(last_size)
                        new_data = f.read(current_size - last_size)
                        try:
                            text = new_data.decode("utf-8", errors="replace")
                        except Exception:
                            text = new_data.decode("latin-1", errors="replace")

                        for line in text.splitlines():
                            if line.strip():
                                level = ""
                                up = line.upper()
                                if "ERROR" in up or "FATAL" in up or "CRIT" in up:
                                    level = "error"
                                    # M6-F10: ERROR 告警通知
                                    asyncio.create_task(notify_error_alert(str(p), line))
                                elif "WARN" in up:
                                    level = "warn"
                                elif "INFO" in up:
                                    level = "info"

                                await websocket.send_json({"text": line, "level": level})

                    last_size = current_size
                elif current_size < last_size:
                    last_size = 0
            except FileNotFoundError:
                await websocket.send_json({"error": "File removed"})
                break
            except Exception:
                pass

    except WebSocketDisconnect:
        pass
