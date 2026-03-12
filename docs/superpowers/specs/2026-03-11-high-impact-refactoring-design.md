# High-Impact Refactoring Design

**Date:** 2026-03-11
**Scope:** 5 refactorings targeting the highest-impact code quality issues in AgentDB

---

## 1. Service List Single Source of Truth

### Problem

Service names and configs are defined independently in three locations:

- `main.py:48` — `SERVICE_CONFIGS` dict with capacity values
- `simulation/deps.py:18` — `ServiceGraph.default_city()` with names and dependency edges
- `dashboard/static/graph.js:26` — hardcoded JS array with names and edges

Adding or removing a service requires updating all three files with no compile-time check for consistency.

### Design

**`ServiceGraph.default_city()` becomes the single source of truth.** It already owns service names and dependency edges. Extend it to include capacity values.

Changes:

1. **`deps.py`** — Add `capacities: dict[str, float]` to `ServiceGraph`. Update `default_city()` to include capacity per service.
2. **`main.py`** — Remove `SERVICE_CONFIGS`. Import `ServiceGraph` and derive seed data from `ServiceGraph.default_city()`.
3. **`app.py`** — Add `GET /api/topology` endpoint returning `{ "services": [...], "edges": [...], "capacities": {...} }` derived from the graph.
4. **`graph.js`** — Fetch `/api/topology` on load. Remove hardcoded `services` and `edges` arrays.
5. **`main.py:broadcast_tick()`** — Iterate over `graph.services` instead of a local dict.

### Invariant

After this change, adding a new service means editing one place: `ServiceGraph.default_city()` in `deps.py`. The seed logic, simulation engine, dashboard API, and JS canvas all derive from it.

---

## 2. AgentRunner Extraction

### Problem

`main.py` contains a 90+ line nested async function `run_agents()` inside `main()`. It mixes three concerns:

1. LangChain message parsing and agent invocation
2. Broadcasting buffered file/overlay events
3. Agent status update broadcasting

This makes `main.py` hard to read, test, and modify. The inline `from langchain_core.messages import ...` hides a dependency.

### Design

**New file: `src/agentdb/agents/runner.py`**

```python
class AgentRunner:
    def __init__(
        self,
        swarm,
        broadcaster: Broadcaster,
        engine: SimulationEngine,
        event_buffer: list,
        agent_names: list[str],
    ):
        ...
        self._cycle_counter = 0

    async def run_cycle(self) -> None:
        """Run one agent decision cycle. Broadcasts status before/during/after."""
        ...
```

Responsibilities:

- `run_cycle()` consolidates all logic currently in `run_agents()`
- LangChain imports move to module-level in `runner.py`
- Message parsing, event forwarding, and status broadcasting become private methods
- `cycle_counter` becomes instance state instead of a `nonlocal` variable

**`main.py` after extraction:**

```python
runner = AgentRunner(swarm, broadcaster, engine, event_buffer, all_agent_names)

async def simulation_loop():
    while True:
        await engine.step()
        await broadcast_tick()
        if agent_task is None or agent_task.done():
            agent_task = asyncio.create_task(runner.run_cycle())
        await asyncio.sleep(TICK_INTERVAL)
```

`main()` becomes ~50 lines of wiring with no business logic.

### Testing

`AgentRunner` can be tested with a mock swarm and broadcaster, which is not possible today since `run_agents()` is a closure.

---

## 3. Subprocess Isolation for Evaluator

### Problem

`simulation/evaluator.py:43` runs agent-written code via in-process code execution with full access to Python builtins. An agent that writes malicious code into a service handler would have it run during the next tick.

### Design

**Replace in-process execution with subprocess execution.**

The evaluator spawns a child Python process for each service evaluation. The child receives the code and arguments, runs in isolation, and returns the result as JSON.

#### Runner script

A constant string in `evaluator.py` containing a minimal Python script. The child process:

- Reads JSON from stdin (code, load, config)
- Compiles and runs the code in a namespace with a restricted builtins whitelist (only safe functions like `len`, `dict`, `float`, `round`, `min`, `max`, etc.)
- Calls `handle_load(load, config)` and prints the result as JSON to stdout

#### Evaluator changes

- `evaluate()` spawns `subprocess.Popen` with the runner script
- Passes code + args via stdin as JSON
- Reads stdout with `timeout=5`, parses JSON into `ServiceResult`
- On timeout: kills the process, returns `ServiceResult` with status `"failed"`
- On parse error or crash: same fallback

#### Properties

- **Isolation:** Separate process, restricted builtins whitelist, no filesystem/network access from within the script
- **Timeout:** 5 seconds per evaluation, hard kill on expiry
- **Overhead:** ~50-100ms per service per tick. With 4 services and 5-second ticks, total overhead is ~200-400ms per tick (acceptable)
- **Dependencies:** None (stdlib `subprocess`, `json`, `sys`)
- **Platform:** Works on macOS (Darwin) and Linux
- **Upgrade path:** Can add `resource.setrlimit()` in child or swap to a process pool if latency becomes an issue

#### What changes

- `evaluator.py` — rewrite `evaluate()` to use subprocess
- `engine.py` — `evaluate()` becomes sync (subprocess is blocking); wrap call in `asyncio.to_thread()` if engine needs to stay async

#### What does not change

- `ServiceResult` dataclass — unchanged
- `CityTools` — unchanged
- Service code contract (`handle_load(load, config) -> dict`) — unchanged
- Test fixtures — update `test_evaluator.py` to test subprocess path

---

## 4. incident:active_count Race Fix

### Problem

Two writers target the same KV key `incident:active_count`:

- `simulation/engine.py:117-122` — overwrites it each tick with the count of services in `"failed"` state
- `agents/tools.py:155-156` — increments it by 1 when an agent creates an incident

The engine's overwrite erases any increment from `create_incident()`. The two definitions also disagree semantically: one counts currently-failed services, the other counts total incidents created.

### Design

**Split into two keys with distinct semantics:**

| Key | Owner | Meaning |
|-----|-------|---------|
| `incident:active_count` | `SimulationEngine` (exclusive) | Number of services currently in `"failed"` state |
| `incident:total_created` | `CityTools.create_incident()` | Monotonic counter of incidents ever created |

Changes:

1. **`agents/tools.py`** — In `create_incident()`, change `incident:active_count` to `incident:total_created`.
2. **`simulation/engine.py`** — No change (already correct for its semantics).

This is a two-line fix.

---

## 5. AuditLog Integration

### Problem

`db/audit.py` defines `AuditLog` with `log()`, `track()`, and `query()` methods. It is fully tested (`test_audit.py`) but never instantiated or used. It also lacks the `threading.Lock` parameter that `VirtualFS` and `KVStore` use for thread safety.

### Design

#### Thread safety

Add `lock` parameter matching the pattern in `VirtualFS` and `KVStore`:

```python
class AuditLog:
    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock | None = None):
        self._conn = conn
        self._lock = lock or threading.Lock()
```

Wrap `self._conn.execute()` + `self._conn.commit()` calls in `with self._lock:`.

#### Wiring into CityTools

`CityTools` gains an optional `audit: AuditLog | None` parameter. When present, each tool method is wrapped:

```python
def read_service_status(self, service_name: str) -> str:
    with self._audit_ctx("read_service_status", service_name):
        ...  # existing logic
```

Where `_audit_ctx` is a thin wrapper around `self._audit.track()` that no-ops if audit is None.

#### API endpoint

New endpoint in `app.py`:

```
GET /api/audit?name=<tool_name>&limit=50
```

Returns recent tool call records as JSON. Filterable by tool name.

#### Wiring in main.py

```python
audit = AuditLog(conn, lock=db_lock)
# pass to CityTools via build_swarm or directly
```

---

## Files Changed (Summary)

| File | Changes |
|------|---------|
| `simulation/deps.py` | Add `capacities` to `ServiceGraph`, update `default_city()` |
| `main.py` | Remove `SERVICE_CONFIGS`, derive from graph, instantiate `AgentRunner`, wire `AuditLog` |
| `agents/runner.py` | **New file** — `AgentRunner` class |
| `simulation/evaluator.py` | Rewrite `evaluate()` to use subprocess |
| `agents/tools.py` | Rename `incident:active_count` to `incident:total_created`, add audit integration |
| `db/audit.py` | Add thread safety (`lock` parameter) |
| `dashboard/app.py` | Add `/api/topology` and `/api/audit` endpoints |
| `dashboard/static/graph.js` | Fetch topology from API instead of hardcoding |
| `tests/test_evaluator.py` | Update for subprocess-based evaluator |
| `tests/test_audit.py` | Update for lock parameter |
| `tests/test_app_api.py` | Add tests for new endpoints |

---

## Out of Scope

These items from the full analysis are deferred (medium/low impact):

- `deploy_staging`/`patch_file` duplication (tools.py)
- `OverlayFS` missing lock
- `list_prefix("")` full table scan
- Test fixture consolidation in conftest.py
- Dead code cleanup (main.py:128, vestigial `conn` param)
- `build_fs_tree` depth limit
- JS `var` re-declarations
- `deque` for BFS in deps.py
