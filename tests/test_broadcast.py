import asyncio
from agentdb.dashboard.broadcast import Broadcaster


async def test_subscribe_and_broadcast():
    b = Broadcaster()
    queue = b.subscribe()
    await b.broadcast("tick", {"tick": 1})
    msg = queue.get_nowait()
    assert '"tick"' in msg
    assert b.connection_count == 1


async def test_unsubscribe():
    b = Broadcaster()
    queue = b.subscribe()
    b.unsubscribe(queue)
    assert b.connection_count == 0


async def test_broadcast_to_multiple():
    b = Broadcaster()
    q1 = b.subscribe()
    q2 = b.subscribe()
    await b.broadcast("test", {"data": "hello"})
    assert not q1.empty()
    assert not q2.empty()
