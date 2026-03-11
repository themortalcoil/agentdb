"""AgentDB City Simulation — entry point.

Initializes the SQLite-backed AgentFS, seeds city services and state,
starts the simulation engine, and serves the FastAPI dashboard on port 8000.
"""

import asyncio
import json
import os
import sqlite3
import textwrap
import threading
import traceback

import uvicorn

from agentdb.db.schema import init_db
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS
from agentdb.simulation.engine import SimulationEngine
from agentdb.dashboard.broadcast import Broadcaster
from agentdb.dashboard.app import create_app

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("AGENTDB_DB", "city.db")
TICK_INTERVAL = float(os.environ.get("TICK_INTERVAL", "5"))

SERVICE_CODE = textwrap.dedent("""\
    def handle_load(load: float, config: dict) -> dict:
        capacity = config.get("capacity", 1.0)
        utilization = load / capacity if capacity > 0 else float("inf")
        if utilization > 1.2:
            status = "failed"
        elif utilization > 0.9:
            status = "degraded"
        else:
            status = "ok"
        return {
            "status": status,
            "capacity": capacity,
            "metrics": {"utilization": round(utilization, 3)},
        }
""")

SERVICE_CONFIGS: dict[str, dict] = {
    "power-grid": {"capacity": 1.0},
    "water-system": {"capacity": 0.8},
    "traffic-control": {"capacity": 0.6},
    "comms-network": {"capacity": 0.9},
}


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------
def seed_services(fs: VirtualFS) -> None:
    """Write default handle_load code and config.json for each service."""
    for name, config in SERVICE_CONFIGS.items():
        fs.write_file(f"/city/services/{name}/main.py", SERVICE_CODE)
        fs.write_file(f"/city/services/{name}/config.json", json.dumps(config))


def seed_kv_state(kv: KVStore) -> None:
    """Populate initial KV entries for city state."""
    initial: dict[str, str] = {
        "city:population": "10000",
        "city:budget": "100000",
    }
    for name in SERVICE_CONFIGS:
        initial[f"service:{name}:status"] = "ok"
        initial[f"service:{name}:load"] = "0.5"
    kv.set_many(initial)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
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

    # 3. Seed city
    seed_services(fs)
    seed_kv_state(kv)

    # 4. Simulation engine
    engine = SimulationEngine(conn, fs, kv, seed=42)

    # 5. Broadcaster + event wiring
    broadcaster = Broadcaster()

    def forward_event(event):
        asyncio.ensure_future(
            broadcaster.broadcast("city_event", event.to_dict())
        )

    engine.on_event(forward_event)

    # 6. Optional agent swarm (requires Ollama)
    try:
        from agentdb.agents.swarm import build_swarm
        swarm = build_swarm(fs, kv, overlay)
        print("Agent swarm initialized.")
    except Exception as exc:  # noqa: BLE001
        swarm = None
        print(f"Agent swarm unavailable ({exc}); running without agents.")

    # 7. FastAPI app
    app = create_app(broadcaster, engine=engine)

    # 8. Background simulation loop
    thread_id = "city-sim"

    async def run_agents() -> None:
        """Invoke the agent swarm to observe and act on city state."""
        if swarm is None:
            return
        try:
            from langchain_core.messages import HumanMessage

            prompt = (
                f"Tick {engine.tick}. Check city health. "
                "If any service is degraded or failed, create an incident "
                "and hand off to the appropriate agent. Otherwise report status."
            )
            result = await swarm.ainvoke(
                {"messages": [HumanMessage(content=prompt)]},
                config={"configurable": {"thread_id": thread_id}},
            )
            # Broadcast agent activity to dashboard
            last_msg = result["messages"][-1]
            agent_name = getattr(last_msg, "name", None) or "swarm"
            await broadcaster.broadcast("agent_update", {
                "agent": agent_name,
                "status": "acted",
                "message": last_msg.content[:200] if last_msg.content else "",
                "tick": engine.tick,
            })
            print(f"[tick {engine.tick}] Agent '{agent_name}': {last_msg.content[:120]}")
        except Exception as exc:
            print(f"[tick {engine.tick}] Agent error: {exc}")
            traceback.print_exc()

    agent_task: asyncio.Task | None = None

    async def simulation_loop() -> None:
        nonlocal agent_task
        while True:
            await engine.step()
            # Run agents concurrently — don't block the tick loop
            if agent_task is None or agent_task.done():
                agent_task = asyncio.create_task(run_agents())
            await asyncio.sleep(TICK_INTERVAL)

    loop_task = asyncio.create_task(simulation_loop())

    # 9. Start uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        loop_task.cancel()
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
