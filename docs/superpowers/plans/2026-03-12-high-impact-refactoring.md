# High-Impact Refactoring Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the top 5 code quality issues: service list duplication, god function in main.py, unsafe code evaluation, KV key race condition, and unused AuditLog.

**Architecture:** ServiceGraph becomes single source of truth for services. AgentRunner extracts agent logic from main.py. Evaluator uses subprocess isolation. AuditLog gets thread safety and wires into CityTools.

**Tech Stack:** Python 3.11+, FastAPI, subprocess (stdlib), SQLite, vanilla JS

---

## Chunk 1: Foundation — Single Source of Truth + Race Fix

### Task 1: Add capacities to ServiceGraph

**Files:**
- Modify: `src/agentdb/simulation/deps.py:6-27`
- Modify: `tests/test_deps.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_deps.py`:

```python
def test_default_city_capacities():
    g = ServiceGraph.default_city()
    assert g.capacities == {
        "power-grid": 1.0,
        "water-system": 0.8,
        "traffic-control": 0.6,
        "comms-network": 0.9,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deps.py::test_default_city_capacities -v`
Expected: FAIL with `AttributeError: 'ServiceGraph' has no attribute 'capacities'`

- [ ] **Step 3: Add capacities field to ServiceGraph and update default_city()**

In `src/agentdb/simulation/deps.py`, add `capacities` field to the dataclass and populate it in `default_city()`:

```python
@dataclass
class ServiceGraph:
    """Directed graph of service dependencies.

    An edge from A -> B means A depends on B (B failing affects A).
    """

    services: list[str] = field(default_factory=list)
    edges: dict[str, list[str]] = field(default_factory=dict)
    capacities: dict[str, float] = field(default_factory=dict)

    @classmethod
    def default_city(cls) -> "ServiceGraph":
        services = [
            "power-grid", "water-system", "traffic-control", "comms-network"
        ]
        edges = {
            "power-grid": [],
            "water-system": ["power-grid"],
            "comms-network": ["power-grid"],
            "traffic-control": ["comms-network"],
        }
        capacities = {
            "power-grid": 1.0,
            "water-system": 0.8,
            "traffic-control": 0.6,
            "comms-network": 0.9,
        }
        return cls(services=services, edges=edges, capacities=capacities)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_deps.py -v`
Expected: All PASS (existing tests unchanged, new test passes)

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/simulation/deps.py tests/test_deps.py
git commit -m "feat: add capacities to ServiceGraph for single source of truth"
```

---

### Task 2: Remove SERVICE_CONFIGS from main.py, derive from ServiceGraph

**Files:**
- Modify: `main.py:1-98`

- [ ] **Step 1: Update main.py imports and remove SERVICE_CONFIGS**

Replace the configuration section (lines 28-53) and seed helpers (lines 59-75) with graph-derived logic:

```python
from agentdb.simulation.deps import ServiceGraph

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


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------
def seed_services(fs: VirtualFS, graph: ServiceGraph) -> None:
    """Write default handle_load code and config.json for each service."""
    for name in graph.services:
        capacity = graph.capacities.get(name, 1.0)
        fs.write_file(f"/city/services/{name}/main.py", SERVICE_CODE)
        fs.write_file(f"/city/services/{name}/config.json", json.dumps({"capacity": capacity}))


def seed_kv_state(kv: KVStore, graph: ServiceGraph) -> None:
    """Populate initial KV entries for city state."""
    initial: dict[str, str] = {
        "city:population": "10000",
        "city:budget": "100000",
    }
    for name in graph.services:
        initial[f"service:{name}:status"] = "ok"
        initial[f"service:{name}:load"] = "0.5"
    kv.set_many(initial)
```

- [ ] **Step 2: Update main() to use graph**

In the `main()` function, create the graph early and pass it through:

```python
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
```

- [ ] **Step 3: Update broadcast_tick() to use graph instead of SERVICE_CONFIGS**

Replace the `broadcast_tick()` closure to use `graph`:

```python
    async def broadcast_tick() -> None:
        """Broadcast current tick + service states to all dashboard clients."""
        services = {}
        for name in graph.services:
            services[name] = {
                "status": kv.get(f"service:{name}:status", "ok"),
                "load": float(kv.get(f"service:{name}:load", "0.5")),
                "capacity": float(kv.get(f"service:{name}:capacity", "1.0")),
            }
        await broadcaster.broadcast("tick", {
            "tick": engine.tick,
            "services": services,
        })
```

- [ ] **Step 4: Fix agent_names derivation (remove dead code on lines 128-129)**

Replace:
```python
    all_agent_names = list(SERVICE_CONFIGS.keys())  # not agents, but we want the 4 agent names
    all_agent_names = ["mayor", "engineer", "monitor", "fixer"]
```

With:
```python
    from agentdb.agents.definitions import AGENT_CONFIGS
    all_agent_names = list(AGENT_CONFIGS.keys())
```

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: All tests pass. No test directly tests main.py wiring, but engine/evaluator tests exercise the same code paths.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "refactor: derive service configs from ServiceGraph, remove SERVICE_CONFIGS"
```

---

### Task 3: Add /api/topology endpoint

**Files:**
- Modify: `src/agentdb/dashboard/app.py:36`
- Modify: `tests/test_app_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_app_api.py`:

```python
def test_api_topology(app_fixtures):
    client, _, _ = app_fixtures
    resp = client.get("/api/topology")
    assert resp.status_code == 200
    data = resp.json()
    assert "services" in data
    assert "edges" in data
    assert "capacities" in data
    assert "power-grid" in data["services"]
    assert len(data["services"]) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app_api.py::test_api_topology -v`
Expected: FAIL with 404

- [ ] **Step 3: Add the endpoint to app.py**

In `src/agentdb/dashboard/app.py`, add the import at the top:

```python
from agentdb.simulation.deps import ServiceGraph
```

Add the endpoint inside `create_app()`, before `return app`:

```python
    @app.get("/api/topology")
    async def get_topology():
        g = ServiceGraph.default_city()
        return {
            "services": g.services,
            "edges": g.edges,
            "capacities": g.capacities,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/dashboard/app.py tests/test_app_api.py
git commit -m "feat: add /api/topology endpoint for service graph"
```

---

### Task 4: Update graph.js to fetch topology from API

**Files:**
- Modify: `src/agentdb/dashboard/static/graph.js:5-59`

- [ ] **Step 1: Replace hardcoded arrays with fetch**

Replace lines 26-39 (the hardcoded `services` and `edges` arrays):

```javascript
  // ---- Service nodes (populated from /api/topology) ----
  var services = [];
  var edges = [];
```

Replace the `init()` function (lines 271-281) with:

```javascript
  function init() {
    canvas = document.getElementById("cityCanvas");
    if (!canvas) return;
    ctx = canvas.getContext("2d");

    canvas.addEventListener("click", handleClick);
    window.addEventListener("resize", resize);

    // Fetch topology from API, then start rendering
    fetch("/api/topology")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        services = data.services.map(function (id) {
          return {
            id: id,
            label: id.split("-").map(function (w) {
              return w.charAt(0).toUpperCase() + w.slice(1);
            }).join(" "),
            status: "ok",
            load: 0.5,
            capacity: data.capacities[id] || 1.0,
            x: 0,
            y: 0
          };
        });

        // Convert edges dict {child: [parents]} to [{from: parent, to: child}]
        edges = [];
        Object.keys(data.edges).forEach(function (child) {
          data.edges[child].forEach(function (parent) {
            edges.push({ from: parent, to: child });
          });
        });

        resize();
        draw();
      })
      .catch(function (err) {
        console.error("Failed to load topology:", err);
      });
  }
```

- [ ] **Step 2: Update layoutNodes to handle dynamic service count**

The current `layoutNodes` hardcodes 4 positions. Replace it with a circular layout:

```javascript
  function layoutNodes(w, h) {
    var cx = w / 2;
    var cy = h / 2;
    var r = Math.min(w, h) * 0.3;

    for (var i = 0; i < services.length; i++) {
      var angle = -Math.PI / 2 + (2 * Math.PI * i) / services.length;
      services[i].x = cx + r * Math.cos(angle);
      services[i].y = cy + r * Math.sin(angle);
    }
  }
```

- [ ] **Step 3: Manual test**

Start the server (`python main.py`), open `http://localhost:8000`, verify the graph renders with the same 4 services and edges.

- [ ] **Step 4: Commit**

```bash
git add src/agentdb/dashboard/static/graph.js
git commit -m "refactor: fetch service topology from API instead of hardcoding"
```

---

### Task 5: Fix incident:active_count race condition

**Files:**
- Modify: `src/agentdb/agents/tools.py:155-156`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write test for the new key name**

Add to `tests/test_tools.py`:

```python
def test_create_incident_uses_total_created_key(city_tools):
    city_tools.create_incident(
        service="power-grid",
        description="Test incident",
        severity="high",
    )
    # Should use incident:total_created, NOT incident:active_count
    total = city_tools.kv.get("incident:total_created")
    assert total == "1"
    # active_count should not be touched by tools
    active = city_tools.kv.get("incident:active_count")
    assert active is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools.py::test_create_incident_uses_total_created_key -v`
Expected: FAIL — `incident:total_created` returns None, `incident:active_count` returns "1"

- [ ] **Step 3: Fix the key name in tools.py**

In `src/agentdb/agents/tools.py`, replace lines 155-156:

```python
        count = int(self.kv.get("incident:total_created", "0")) + 1
        self.kv.set("incident:total_created", str(count))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/agents/tools.py tests/test_tools.py
git commit -m "fix: split incident:active_count into separate keys to prevent race"
```

---

## Chunk 2: AuditLog Thread Safety + Integration

### Task 6: Add thread safety to AuditLog

**Files:**
- Modify: `src/agentdb/db/audit.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write test for lock parameter**

Add to `tests/test_audit.py`:

```python
import threading


def test_audit_accepts_lock(db):
    lock = threading.Lock()
    audit = AuditLog(db, lock=lock)
    audit.log("write_file", '{"path": "/city/services/power-grid/main.py"}', '"ok"')
    results = audit.query()
    assert len(results) == 1


def test_audit_default_lock(db):
    """AuditLog should work without an explicit lock (creates its own)."""
    audit = AuditLog(db)
    audit.log("tool", "{}", '"ok"')
    results = audit.query()
    assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_audit.py::test_audit_accepts_lock -v`
Expected: FAIL — `__init__() got an unexpected keyword argument 'lock'`

- [ ] **Step 3: Add lock parameter to AuditLog**

Replace `src/agentdb/db/audit.py` with thread-safe version:

```python
"""Tool call audit trail backed by AgentFS tool_calls table."""

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class ToolCallTracker:
    """Mutable tracker used inside the track context manager."""
    result: str | None = None
    error: str | None = None


class AuditLog:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock | None = None):
        self._conn = conn
        self._lock = lock or threading.Lock()

    def log(
        self,
        name: str,
        parameters: str,
        result: str | None,
        error: str | None = None,
        agent_name: str | None = None,
    ) -> int | None:
        now_ms = int(time.time() * 1000)
        with self._lock:
            cursor = self._conn.execute(
                """INSERT INTO tool_calls
                   (agent_name, name, parameters, result, error, started_at, completed_at, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_name, name, parameters, result, error, now_ms, now_ms, 0),
            )
            self._conn.commit()
        return cursor.lastrowid

    @contextmanager
    def track(self, name: str, parameters: str):
        tracker = ToolCallTracker()
        started = int(time.time() * 1000)
        try:
            yield tracker
        except Exception as e:
            tracker.error = str(e)
            raise
        finally:
            completed = int(time.time() * 1000)
            with self._lock:
                self._conn.execute(
                    """INSERT INTO tool_calls
                       (agent_name, name, parameters, result, error, started_at, completed_at, duration_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (None, name, parameters, tracker.result, tracker.error,
                     started, completed, completed - started),
                )
                self._conn.commit()

    def query(
        self,
        name: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM tool_calls"
        params: list = []
        if name:
            sql += " WHERE name = ?"
            params.append(name)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run all audit tests**

Run: `pytest tests/test_audit.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/db/audit.py tests/test_audit.py
git commit -m "feat: add thread safety to AuditLog with lock parameter"
```

---

### Task 7: Wire AuditLog into CityTools

**Files:**
- Modify: `src/agentdb/agents/tools.py:1-29`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write test for audit integration**

Add to `tests/test_tools.py`:

```python
from agentdb.db.audit import AuditLog


@pytest.fixture
def audited_city_tools(db):
    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    audit = AuditLog(db)
    return CityTools(fs=fs, kv=kv, overlay=overlay, audit=audit), audit


def test_audit_logs_tool_calls(audited_city_tools):
    tools, audit = audited_city_tools
    tools.kv.set("city:population", "10000")
    tools.read_city_state()
    results = audit.query(name="read_city_state")
    assert len(results) == 1
    assert results[0]["name"] == "read_city_state"
    assert results[0]["duration_ms"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools.py::test_audit_logs_tool_calls -v`
Expected: FAIL — `__init__() got an unexpected keyword argument 'audit'`

- [ ] **Step 3: Add audit parameter and tracking to CityTools**

In `src/agentdb/agents/tools.py`, add the import at the top:

```python
from contextlib import contextmanager

from agentdb.db.audit import AuditLog
```

Update `__init__` to accept audit:

```python
    def __init__(
        self,
        fs: VirtualFS,
        kv: KVStore,
        overlay: OverlayFS,
        event_buffer: list | None = None,
        audit: AuditLog | None = None,
    ):
        self.fs = fs
        self.kv = kv
        self.overlay = overlay
        self._incident_counter = 0
        self._events = event_buffer if event_buffer is not None else []
        self._audit = audit
```

Add the audit context helper:

```python
    @contextmanager
    def _audit_ctx(self, name: str, params: str = ""):
        if self._audit is None:
            yield
            return
        with self._audit.track(name, params) as tracker:
            yield tracker
```

Then wrap each public tool method. For example, `read_city_state`:

```python
    def read_city_state(self) -> str:
        """Read current city state: service statuses, agent states, priorities."""
        with self._audit_ctx("read_city_state"):
            items = self.kv.list_prefix("city:")
            items += self.kv.list_prefix("service:")
            items += self.kv.list_prefix("incident:")
            items += self.kv.list_prefix("mayor:")
            return json.dumps(dict(items), indent=2)
```

Apply the same `with self._audit_ctx("method_name", params_str):` pattern to all public methods: `set_priority`, `assign_task`, `write_file`, `read_file`, `deploy_staging`, `run_tests`, `read_metrics`, `check_health`, `create_incident`, `patch_file`, `hotfix_prod`, `rollback`.

- [ ] **Step 4: Run all tools tests**

Run: `pytest tests/test_tools.py -v`
Expected: All PASS (existing tests use `city_tools` fixture without audit — works because audit=None is the default)

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/agents/tools.py tests/test_tools.py
git commit -m "feat: wire AuditLog into CityTools with opt-in tracking"
```

---

### Task 8: Add /api/audit endpoint

**Files:**
- Modify: `src/agentdb/dashboard/app.py`
- Modify: `tests/test_app_api.py`

- [ ] **Step 1: Write the failing test**

Update the `app_fixtures` fixture in `tests/test_app_api.py` to include audit:

```python
from agentdb.db.audit import AuditLog

@pytest.fixture
def app_fixtures():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    fs = VirtualFS(conn)
    broadcaster = Broadcaster()
    audit = AuditLog(conn)
    app = create_app(broadcaster, engine=None, fs=fs, audit=audit)
    client = TestClient(app)
    return client, fs, conn, audit
```

Update all existing tests to unpack 4 values (add `_` for unused audit):
```python
def test_api_file_returns_content(app_fixtures):
    client, fs, _, _ = app_fixtures
    ...
```

Add new tests:

```python
def test_api_audit_empty(app_fixtures):
    client, _, _, _ = app_fixtures
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_audit_with_data(app_fixtures):
    client, _, _, audit = app_fixtures
    audit.log("write_file", '{"path": "/city/test"}', '"ok"')
    audit.log("read_file", '{"path": "/city/test"}', '"data"')
    resp = client.get("/api/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2

    # Filter by name
    resp = client.get("/api/audit", params={"name": "write_file"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "write_file"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app_api.py::test_api_audit_empty -v`
Expected: FAIL — either 404 or TypeError on `create_app`

- [ ] **Step 3: Add audit parameter to create_app and the endpoint**

In `src/agentdb/dashboard/app.py`, update the signature:

```python
def create_app(broadcaster: Broadcaster, engine=None, fs=None, audit=None) -> FastAPI:
```

Add the endpoint inside `create_app()`, before `return app`:

```python
    @app.get("/api/audit")
    async def get_audit(name: str | None = Query(None), limit: int = Query(50)):
        if audit is None:
            return JSONResponse([])
        return JSONResponse(audit.query(name=name, limit=limit))
```

- [ ] **Step 4: Run all app API tests**

Run: `pytest tests/test_app_api.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/dashboard/app.py tests/test_app_api.py
git commit -m "feat: add /api/audit endpoint for tool call history"
```

---

## Chunk 3: Subprocess Isolation for Evaluator

### Task 9: Rewrite evaluator to use subprocess

**Files:**
- Modify: `src/agentdb/simulation/evaluator.py`
- Modify: `tests/test_evaluator.py`

- [ ] **Step 1: Write a new test for subprocess timeout**

Add to `tests/test_evaluator.py`:

```python
INFINITE_LOOP_SERVICE = '''
def handle_load(load: float, config: dict) -> dict:
    while True:
        pass
'''


def test_evaluate_infinite_loop_times_out(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", INFINITE_LOOP_SERVICE)
    fs.write_file("/city/services/power-grid/config.json", '{}')
    evaluator = ServiceEvaluator(fs)
    result = evaluator.evaluate("power-grid", load=0.5)
    assert result.status == "failed"
    assert "timeout" in result.error.lower()
```

- [ ] **Step 2: Run test to verify it fails (or hangs with current impl)**

Run: `pytest tests/test_evaluator.py::test_evaluate_infinite_loop_times_out -v --timeout=10`
Expected: Either hangs (current impl has no timeout) or fails.

Note: Install pytest-timeout if not present: `pip install pytest-timeout`

- [ ] **Step 3: Rewrite evaluator.py to use subprocess**

Replace `src/agentdb/simulation/evaluator.py` entirely. The new implementation:

1. Defines `EVAL_TIMEOUT = 5` (seconds)
2. Defines `_RUNNER_SCRIPT` — a Python script string that:
   - Reads JSON from stdin (`{"code": ..., "load": ..., "config": ...}`)
   - Sets up a restricted builtins whitelist (only safe functions: `len`, `dict`, `list`, `float`, `int`, `round`, `range`, `min`, `max`, `abs`, `sum`, `sorted`, `zip`, `map`, `filter`, `isinstance`, `type`, `enumerate`, plus built-in exceptions and constants)
   - Compiles and runs the code in the restricted namespace
   - Calls `handle_load(load, config)` and prints JSON result to stdout
   - Prints `{"__error__": "..."}` for handled errors
3. `ServiceEvaluator.evaluate()`:
   - Reads code and config from VirtualFS (same as before)
   - Spawns `subprocess.Popen([sys.executable, "-c", _RUNNER_SCRIPT])`
   - Passes input via `proc.communicate(input=json_payload, timeout=EVAL_TIMEOUT)`
   - On `TimeoutExpired`: kills process, returns `ServiceResult.failed("Evaluation timeout")`
   - On non-zero exit: returns failed with stderr
   - On success: parses stdout JSON, checks for `__error__` key, returns `ServiceResult`
4. `ServiceResult` dataclass is unchanged

- [ ] **Step 4: Run all evaluator tests**

Run: `pytest tests/test_evaluator.py -v`
Expected: All PASS including the new timeout test

- [ ] **Step 5: Run full test suite to check nothing else broke**

Run: `pytest -v`
Expected: All PASS. The engine tests call `evaluator.evaluate()` indirectly — they should still work since the interface is unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/simulation/evaluator.py tests/test_evaluator.py
git commit -m "security: replace in-process code evaluation with subprocess isolation"
```

---

## Chunk 4: AgentRunner Extraction

### Task 10: Extract AgentRunner class

**Files:**
- Create: `src/agentdb/agents/runner.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Write the test**

Create `tests/test_runner.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from agentdb.agents.runner import AgentRunner


@pytest.fixture
def mock_broadcaster():
    b = MagicMock()
    b.broadcast = AsyncMock()
    return b


@pytest.fixture
def mock_engine():
    e = MagicMock()
    e.tick = 5
    return e


async def test_runner_no_swarm(mock_broadcaster, mock_engine):
    runner = AgentRunner(
        swarm=None,
        broadcaster=mock_broadcaster,
        engine=mock_engine,
        event_buffer=[],
        agent_names=["mayor", "engineer", "monitor", "fixer"],
    )
    await runner.run_cycle()
    # With no swarm, should broadcast "working" then "idle" for all agents
    assert mock_broadcaster.broadcast.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_runner.py::test_runner_no_swarm -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentdb.agents.runner'`

- [ ] **Step 3: Create agents/runner.py**

Create `src/agentdb/agents/runner.py` with the `AgentRunner` class:

- Constructor takes: `swarm`, `broadcaster` (Broadcaster), `engine` (SimulationEngine), `event_buffer` (list), `agent_names` (list[str]), `thread_id` (str, default "city-sim")
- Instance state: `_cycle_counter = 0`
- Public method: `async run_cycle()` — orchestrates one agent decision cycle
- Private methods:
  - `_invoke_swarm()` — sends the prompt to the swarm and returns the result
  - `_process_messages(result)` — parses AIMessage objects, broadcasts `agent_message` events, returns dict of agent_name -> summary
  - `_flush_event_buffer()` — broadcasts buffered CityTools events
  - `_broadcast_agent_statuses(participated)` — sends acted/idle status for each agent
  - `_broadcast_idle_all()` — sends idle status for all agents (used when swarm is None)
- Error handling: catches exceptions from swarm, clears event buffer, broadcasts error status
- Module-level imports: `HumanMessage` and `AIMessage` from `langchain_core.messages`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/agents/runner.py tests/test_runner.py
git commit -m "refactor: extract AgentRunner class from main.py"
```

---

### Task 11: Rewire main.py to use AgentRunner

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Replace run_agents() and wiring with AgentRunner**

Remove the `run_agents()` closure, `cycle_counter`, and inline agent logic. Replace with:

```python
    # 6. Optional agent swarm (requires Ollama)
    event_buffer: list = []
    from agentdb.db.audit import AuditLog
    audit = AuditLog(conn, lock=db_lock)

    try:
        from agentdb.agents.swarm import build_swarm
        swarm = build_swarm(fs, kv, overlay, event_buffer=event_buffer, audit=audit)
        print("Agent swarm initialized.")
    except Exception as exc:  # noqa: BLE001
        swarm = None
        print(f"Agent swarm unavailable ({exc}); running without agents.")

    # 7. Agent runner
    from agentdb.agents.definitions import AGENT_CONFIGS
    from agentdb.agents.runner import AgentRunner
    all_agent_names = list(AGENT_CONFIGS.keys())
    runner = AgentRunner(
        swarm=swarm,
        broadcaster=broadcaster,
        engine=engine,
        event_buffer=event_buffer,
        agent_names=all_agent_names,
    )

    # 8. FastAPI app
    app = create_app(broadcaster, engine=engine, fs=fs, audit=audit)

    # 9. Background simulation loop
    agent_task: asyncio.Task | None = None

    async def simulation_loop() -> None:
        nonlocal agent_task
        while True:
            await engine.step()
            await broadcast_tick()
            if agent_task is None or agent_task.done():
                agent_task = asyncio.create_task(runner.run_cycle())
            await asyncio.sleep(TICK_INTERVAL)

    loop_task = asyncio.create_task(simulation_loop())

    # 10. Start uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        loop_task.cancel()
        conn.close()
```

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "refactor: use AgentRunner in main.py, wire AuditLog"
```

---

### Task 12: Pass AuditLog through build_swarm to CityTools

**Files:**
- Modify: `src/agentdb/agents/swarm.py:40-44`

- [ ] **Step 1: Update build_swarm signature**

In `src/agentdb/agents/swarm.py`, update:

```python
def build_swarm(fs: VirtualFS, kv: KVStore, overlay: OverlayFS,
                event_buffer: list | None = None, audit=None):
    """Build and compile the LangGraph Swarm with all city agents."""
    city_tools = CityTools(fs=fs, kv=kv, overlay=overlay,
                           event_buffer=event_buffer, audit=audit)
```

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`
Expected: All PASS (test_swarm.py doesn't test build_swarm directly due to Ollama dependency)

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/agents/swarm.py
git commit -m "feat: pass AuditLog through build_swarm to CityTools"
```

---

### Task 13: Clean up /api/state to use engine method

**Files:**
- Modify: `src/agentdb/simulation/engine.py`
- Modify: `src/agentdb/dashboard/app.py:98-109`
- Modify: `tests/test_engine.py`

- [ ] **Step 1: Write test for get_full_state method**

Add to `tests/test_engine.py`:

```python
async def test_get_full_state(db):
    fs, kv = _setup_city(db)
    engine = SimulationEngine(db, fs, kv, seed=42)
    await engine.step()
    state = engine.get_full_state()
    assert "state" in state
    assert "tick" in state
    assert state["tick"] == 1
    assert "city:population" in state["state"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_engine.py::test_get_full_state -v`
Expected: FAIL — `AttributeError: 'SimulationEngine' has no attribute 'get_full_state'`

- [ ] **Step 3: Add get_full_state to SimulationEngine**

In `src/agentdb/simulation/engine.py`, add after the `resume()` method:

```python
    def get_full_state(self) -> dict:
        """Return full simulation state for the dashboard API."""
        items = self._kv.list_prefix("")
        return {"state": dict(items), "tick": self.tick, "paused": self.paused}
```

- [ ] **Step 4: Update /api/state endpoint in app.py**

Replace the `/api/state` endpoint:

```python
    @app.get("/api/state")
    async def get_state():
        if engine:
            return engine.get_full_state()
        return {"state": {}, "tick": 0, "paused": False}
```

Remove the inline `from agentdb.db.kvstore import KVStore` import.

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/simulation/engine.py src/agentdb/dashboard/app.py tests/test_engine.py
git commit -m "refactor: add get_full_state() to engine, remove _conn access from app.py"
```

---

### Task 14: Final integration verification

- [ ] **Step 1: Run full test suite**

Run: `pytest -v`
Expected: All PASS

- [ ] **Step 2: Start the server and verify dashboard loads**

Run: `python main.py`

Check:
- Dashboard loads at `http://localhost:8000`
- Canvas graph renders (fetched from `/api/topology`)
- `/api/topology` returns JSON with services, edges, capacities
- `/api/audit` returns `[]` (no tool calls yet)
- `/api/state` returns state dict with tick counter

- [ ] **Step 3: Final commit if any tweaks needed**

```bash
git add -A
git commit -m "chore: final integration fixes for high-impact refactoring"
```
