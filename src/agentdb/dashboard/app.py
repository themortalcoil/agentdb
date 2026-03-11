"""FastAPI application with WebSocket endpoint and static file serving."""

import asyncio
import json
import posixpath
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from agentdb.dashboard.broadcast import Broadcaster

STATIC_DIR = Path(__file__).parent / "static"


def build_fs_tree(fs) -> dict:
    """Build a nested dict tree from VirtualFS. Files=int(size), dirs=dict."""
    def _walk(path: str) -> dict:
        tree = {}
        for name in fs.list_dir(path):
            if name.startswith("__"):  # skip __overlay__ internal namespace
                continue
            child = f"{path}/{name}" if path != "/" else f"/{name}"
            content = fs.read_file(child)
            if content is not None:
                tree[name] = len(content.encode())
            else:
                subtree = _walk(child)
                if subtree:
                    tree[name] = subtree
        return tree
    return _walk("/")


def create_app(broadcaster: Broadcaster, engine=None, fs=None) -> FastAPI:
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
            if fs:
                tree = build_fs_tree(fs)
                snapshot = json.dumps({"type": "fs_snapshot", "data": {"tree": tree}})
                await ws.send_text(snapshot)

            async def read_client():
                try:
                    while True:
                        data = await ws.receive_text()
                        try:
                            msg = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if engine and msg.get("action") == "pause":
                            engine.pause()
                        elif engine and msg.get("action") == "resume":
                            engine.resume()
                except WebSocketDisconnect:
                    pass

            read_task = asyncio.create_task(read_client())

            while True:
                message = await queue.get()
                try:
                    await ws.send_text(message)
                except RuntimeError:
                    break
        except WebSocketDisconnect:
            pass
        finally:
            broadcaster.unsubscribe(queue)
            if read_task is not None:
                read_task.cancel()

    @app.get("/api/file")
    async def get_file(path: str = Query(...)):
        normalized = posixpath.normpath(path)
        if not normalized.startswith("/city/"):
            return JSONResponse({"error": "Path must start with /city/"}, status_code=400)
        if fs is None:
            return JSONResponse({"error": "Filesystem not available"}, status_code=500)
        content = fs.read_file(normalized)
        if content is None:
            return JSONResponse({"error": "File not found"}, status_code=404)
        return PlainTextResponse(content)

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
