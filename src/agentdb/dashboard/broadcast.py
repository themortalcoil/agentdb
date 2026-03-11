"""WebSocket event broadcaster."""

import asyncio
import json


class Broadcaster:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self):
        self._connections: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._connections.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._connections.discard(queue)

    async def broadcast(self, event_type: str, data: dict) -> None:
        message = json.dumps({"type": event_type, "data": data})
        dead: list[asyncio.Queue] = []
        for queue in self._connections:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead.append(queue)
        for q in dead:
            self._connections.discard(q)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
