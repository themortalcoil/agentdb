"""AgentDB City Simulation — entry point.

Initializes the SQLite-backed AgentFS, seeds city services and state,
starts the simulation engine, and serves the FastAPI dashboard on port 8000.
"""

import asyncio
import sqlite3
import threading

import uvicorn

from agentdb.config import DB_PATH, TICK_INTERVAL, HOST, PORT
from agentdb.seed import seed_services, seed_kv_state
from agentdb.db.schema import init_db
from agentdb.db.audit import AuditLog
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS
from agentdb.simulation.engine import SimulationEngine
from agentdb.simulation.deps import ServiceGraph
from agentdb.agents.definitions import AGENT_CONFIGS
from agentdb.agents.runner import AgentRunner
from agentdb.dashboard.broadcast import Broadcaster
from agentdb.dashboard.app import create_app


async def main() -> None:
    # 1. Database
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    # 2. Core layers
    db_lock = threading.Lock()
    fs = VirtualFS(conn, lock=db_lock)
    kv = KVStore(conn, lock=db_lock)
    overlay = OverlayFS(conn, fs)

    # 3. Service graph (single source of truth)
    graph = ServiceGraph.default_city()

    # 4. Seed city
    seed_services(fs, graph)
    seed_kv_state(kv, graph)

    # 5. Simulation engine
    engine = SimulationEngine(conn, fs, kv, seed=42, graph=graph)

    # 6. Broadcaster + event wiring
    broadcaster = Broadcaster()

    def forward_event(event):
        asyncio.ensure_future(
            broadcaster.broadcast("city_event", event.to_dict())
        )

    engine.on_event(forward_event)

    # 7. AuditLog + agent swarm (requires Ollama)
    audit = AuditLog(conn, lock=db_lock)
    event_buffer: list = []

    city_tools = None
    try:
        from agentdb.agents.swarm import build_swarm
        swarm, city_tools = build_swarm(fs, kv, overlay, event_buffer=event_buffer, audit=audit)
        print("Agent swarm initialized.")
    except Exception as exc:  # noqa: BLE001
        import traceback as _tb
        swarm = None
        print(f"Agent swarm unavailable ({exc}); running without agents.")
        _tb.print_exc()

    # 8. Agent runner
    all_agent_names = list(AGENT_CONFIGS.keys())
    runner = AgentRunner(
        swarm=swarm,
        broadcaster=broadcaster,
        engine=engine,
        event_buffer=event_buffer,
        agent_names=all_agent_names,
        kv=kv,
        fs=fs,
        city_tools=city_tools,
    )

    # 9. FastAPI app
    app = create_app(
        broadcaster,
        engine=engine,
        fs=fs,
        audit=audit,
        agent_names=all_agent_names,
    )

    # 10. Background simulation loop
    async def broadcast_tick() -> None:
        """Broadcast current tick + service states to all dashboard clients."""
        services = {}
        for name in graph.services:
            load_raw = kv.get(f"service:{name}:load", "0.5")
            cap_raw = kv.get(f"service:{name}:capacity", "1.0")
            services[name] = {
                "status": kv.get(f"service:{name}:status", "ok"),
                "load": float(load_raw or "0.5"),
                "capacity": float(cap_raw or "1.0"),
            }
        await broadcaster.broadcast("tick", {
            "tick": engine.tick,
            "services": services,
        })

    agent_task: asyncio.Task | None = None

    async def simulation_loop() -> None:
        nonlocal agent_task
        while True:
            await engine.step()
            await broadcast_tick()
            # Run agents concurrently — don't block the tick loop
            if agent_task is None or agent_task.done():
                # Log any exception from the previous cycle
                if agent_task is not None and not agent_task.cancelled():
                    exc = agent_task.exception()
                    if exc is not None:
                        import traceback as _tb
                        print(f"[runner] unhandled exception in run_cycle: {exc}")
                        _tb.print_exception(type(exc), exc, exc.__traceback__)
                agent_task = asyncio.create_task(runner.run_cycle())
            await asyncio.sleep(TICK_INTERVAL)

    loop_task = asyncio.create_task(simulation_loop())

    # 11. Start uvicorn
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        loop_task.cancel()
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
