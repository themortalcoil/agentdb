from agentdb.db.kvstore import KVStore
from agentdb.db.filesystem import VirtualFS
from agentdb.simulation.engine import SimulationEngine

POWER_GRID_CODE = '''
def handle_load(load: float, config: dict) -> dict:
    capacity = config.get("capacity", 1.0)
    status = "ok" if load <= capacity else "degraded"
    return {
        "status": status,
        "capacity": capacity,
        "metrics": {"utilization": load / capacity},
    }
'''


def _setup_city(db):
    """Seed the city with working services."""
    fs = VirtualFS(db)
    kv = KVStore(db)
    services = [
        "power-grid", "water-system", "traffic-control", "comms-network"
    ]
    for svc in services:
        fs.write_file(f"/city/services/{svc}/main.py", POWER_GRID_CODE)
        fs.write_file(f"/city/services/{svc}/config.json", '{"capacity": 1.0}')
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
    kv.set("city:population", "10000")
    kv.set("city:budget", "100000")
    return fs, kv


def test_engine_creation(db):
    fs, kv = _setup_city(db)
    engine = SimulationEngine(db, fs, kv, seed=42)
    assert engine.tick == 0
    assert engine.paused is False


async def test_single_tick(db):
    fs, kv = _setup_city(db)
    events_received = []
    engine = SimulationEngine(db, fs, kv, seed=42)
    engine.on_event(lambda e: events_received.append(e))
    await engine.step()
    assert engine.tick == 1
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        load = kv.get(f"service:{svc}:load")
        assert load is not None


async def test_pause_resume(db):
    fs, kv = _setup_city(db)
    engine = SimulationEngine(db, fs, kv, seed=42)
    engine.pause()
    assert engine.paused is True
    await engine.step()  # no-op when paused
    assert engine.tick == 0
    engine.resume()
    await engine.step()
    assert engine.tick == 1


async def test_broken_service_generates_failure_event(db):
    fs, kv = _setup_city(db)
    fs.write_file(
        "/city/services/power-grid/main.py",
        "def handle_load(l, c): return 1/0",
    )
    events_received = []
    engine = SimulationEngine(db, fs, kv, seed=42)
    engine.on_event(lambda e: events_received.append(e))
    await engine.step()
    failure_events = [
        e for e in events_received if e.event_type.value == "service_failure"
    ]
    assert len(failure_events) >= 1
    assert any(e.service == "power-grid" for e in failure_events)
