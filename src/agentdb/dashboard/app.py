"""FastAPI application with WebSocket endpoint and static file serving."""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from agentdb.dashboard.broadcast import Broadcaster

STATIC_DIR = Path(__file__).parent / "static"


def create_app(broadcaster: Broadcaster, engine=None) -> FastAPI:
    app = FastAPI(title="AgentDB City Dashboard")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return HTMLResponse((STATIC_DIR / "index.html").read_text())

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        queue = broadcaster.subscribe()
        read_task = None
        try:
            async def read_client():
                try:
                    while True:
                        data = await ws.receive_text()
                        msg = json.loads(data)
                        if engine and msg.get("action") == "pause":
                            engine.pause()
                        elif engine and msg.get("action") == "resume":
                            engine.resume()
                except WebSocketDisconnect:
                    pass

            read_task = asyncio.create_task(read_client())

            while True:
                message = await queue.get()
                await ws.send_text(message)
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unsubscribe(queue)
            if read_task is not None:
                read_task.cancel()

    @app.get("/api/state")
    async def get_state():
        if engine:
            from agentdb.db.kvstore import KVStore
            kv = KVStore(engine._conn)
            items = kv.list_prefix("")
            return {
                "state": dict(items),
                "tick": engine.tick,
                "paused": engine.paused,
            }
        return {"state": {}, "tick": 0, "paused": False}

    return app
