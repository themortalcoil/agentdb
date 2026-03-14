# Agent Orchestration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix agent attribution in audit logs, add hybrid orchestrator (deterministic triage + LLM planner), and improve agent prompts so they complete the deploy pipeline.

**Architecture:** Three-phase cycle in `AgentRunner`: (1) deterministic triage reads KV/FS state, (2) LLM planner generates targeted tasks when there's work, (3) targeted dispatch with per-agent instructions. Agent attribution flows through `CityTools.set_current_agent()` to both audit rows and event buffer entries.

**Tech Stack:** Python 3.11, LangGraph Swarm, LangChain, ChatOllama (glm-5:cloud for planner), SQLite, pytest

**Spec:** `docs/superpowers/specs/2026-03-13-agent-orchestration-design.md`

---

## Chunk 1: Attribution + Prompts (Tasks 1-2, 4)

### Task 1: Add agent_name to AuditLog.track()

**Files:**
- Modify: `src/agentdb/db/audit.py:12-62`
- Test: `tests/test_audit.py` (create)

- [ ] **Step 1: Write failing tests for agent_name in track()**

```python
# tests/test_audit.py
from agentdb.db.audit import AuditLog, ToolCallTracker


def test_track_records_agent_name(db):
    """track() should store agent_name when provided."""
    audit = AuditLog(db)
    with audit.track("read_file", "/city/services/power-grid/main.py", agent_name="engineer") as tracker:
        tracker.result = "file contents"
    rows = audit.query(limit=1)
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "engineer"


def test_track_defaults_agent_name_to_none(db):
    """track() should default agent_name to None for backward compatibility."""
    audit = AuditLog(db)
    with audit.track("check_health", "") as tracker:
        tracker.result = "ok"
    rows = audit.query(limit=1)
    assert len(rows) == 1
    assert rows[0]["agent_name"] is None


def test_track_exposes_row_id(db):
    """track() should set row_id on the tracker after insert."""
    audit = AuditLog(db)
    with audit.track("read_file", "/city/test", agent_name="fixer") as tracker:
        tracker.result = "data"
    assert tracker.row_id is not None
    assert isinstance(tracker.row_id, int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_audit.py -v`
Expected: FAIL — `track()` does not accept `agent_name` parameter, `ToolCallTracker` has no `row_id` field

- [ ] **Step 3: Implement agent_name in track() and row_id on tracker**

In `src/agentdb/db/audit.py`:

Add `row_id` field to `ToolCallTracker`:
```python
@dataclass
class ToolCallTracker:
    """Mutable tracker used inside the track context manager."""
    result: str | None = None
    error: str | None = None
    row_id: int | None = None
```

Update `track()` signature and `finally` block to accept `agent_name` and capture `lastrowid`:
```python
@contextmanager
def track(self, name: str, parameters: str, agent_name: str | None = None):
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
            cursor = self._conn.execute(
                """INSERT INTO tool_calls
                   (agent_name, name, parameters, result, error, started_at, completed_at, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_name, name, parameters, tracker.result, tracker.error,
                 started, completed, completed - started),
            )
            self._conn.commit()
            tracker.row_id = cursor.lastrowid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_audit.py -v`
Expected: 3 passed

- [ ] **Step 5: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All tests pass (existing code calls `track(name, params)` with no `agent_name`, which defaults to `None` — backward compatible)

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/db/audit.py tests/test_audit.py
git commit -m "feat: add agent_name param to AuditLog.track() and row_id to tracker"
```

---

### Task 2: Add set_current_agent and agent field to CityTools

**Files:**
- Modify: `src/agentdb/agents/tools.py:15-54`
- Test: `tests/test_tools.py` (existing file — add tests)

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tools.py`:

```python
def test_set_current_agent_flows_to_audit(db):
    """set_current_agent should cause audit rows to record agent_name."""
    from agentdb.db.audit import AuditLog
    from agentdb.db.filesystem import VirtualFS
    from agentdb.db.kvstore import KVStore
    from agentdb.db.overlay import OverlayFS
    from agentdb.agents.tools import CityTools

    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    audit = AuditLog(db)
    tools = CityTools(fs=fs, kv=kv, overlay=overlay, audit=audit)

    tools.set_current_agent("engineer")
    fs.write_file("/city/services/power-grid/main.py", "print('hello')")
    result = tools.read_file("/city/services/power-grid/main.py")
    assert result == "print('hello')"

    rows = audit.query(name="read_file", limit=1)
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "engineer"


def test_set_current_agent_flows_to_event_buffer(db):
    """set_current_agent should cause _emit to include agent field."""
    from agentdb.db.filesystem import VirtualFS
    from agentdb.db.kvstore import KVStore
    from agentdb.db.overlay import OverlayFS
    from agentdb.agents.tools import CityTools

    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    buffer = []
    tools = CityTools(fs=fs, kv=kv, overlay=overlay, event_buffer=buffer)

    tools.set_current_agent("fixer")
    fs.write_file("/city/services/power-grid/main.py", "old code")
    tools.write_file("/city/services/power-grid/main.py", "new code")

    # Events emitted by write_file should include agent field
    assert len(buffer) >= 1
    for event in buffer:
        assert event.get("agent") == "fixer"


def test_pop_audit_ids(db):
    """pop_audit_ids should return and clear collected row IDs."""
    from agentdb.db.audit import AuditLog
    from agentdb.db.filesystem import VirtualFS
    from agentdb.db.kvstore import KVStore
    from agentdb.db.overlay import OverlayFS
    from agentdb.agents.tools import CityTools

    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    audit = AuditLog(db)
    tools = CityTools(fs=fs, kv=kv, overlay=overlay, audit=audit)

    tools.set_current_agent("monitor")
    tools.check_health()
    ids = tools.pop_audit_ids()
    assert len(ids) >= 1
    assert all(isinstance(i, int) for i in ids)
    # Second call should return empty
    assert tools.pop_audit_ids() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_tools.py::test_set_current_agent_flows_to_audit tests/test_tools.py::test_set_current_agent_flows_to_event_buffer tests/test_tools.py::test_pop_audit_ids -v`
Expected: FAIL — `set_current_agent` and `pop_audit_ids` don't exist

- [ ] **Step 3: Implement set_current_agent, update _emit and _audit_ctx**

In `src/agentdb/agents/tools.py`, add to `__init__` after `self._audit = audit`:
```python
self._current_agent: str | None = None
self._recent_audit_ids: list[int] = []
```

Add new methods after `__init__`:
```python
def set_current_agent(self, name: str | None) -> None:
    """Set the agent name for attribution on subsequent tool calls."""
    self._current_agent = name

def pop_audit_ids(self) -> list[int]:
    """Return and clear collected audit row IDs."""
    ids = self._recent_audit_ids
    self._recent_audit_ids = []
    return ids
```

Update `_emit` to include agent:
```python
def _emit(self, event_type: str, **kwargs) -> None:
    """Append an event to the event buffer."""
    self._events.append({"type": event_type, "agent": self._current_agent, **kwargs})
```

Update `_audit_ctx` to pass agent_name and collect row IDs:
```python
@contextmanager
def _audit_ctx(self, name: str, params: str = ""):
    if self._audit is None:
        yield
        return
    with self._audit.track(name, params, agent_name=self._current_agent) as tracker:
        yield tracker
    if tracker.row_id is not None:
        self._recent_audit_ids.append(tracker.row_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_tools.py -v`
Expected: All tests pass (new + existing)

- [ ] **Step 5: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All pass — `_emit` now adds `agent` key to events, but existing consumers just ignore extra keys

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/agents/tools.py tests/test_tools.py
git commit -m "feat: add set_current_agent, pop_audit_ids, and agent field to CityTools"
```

---

### Task 3: Update agent prompts

**Files:**
- Modify: `src/agentdb/agents/definitions.py:15-82`

- [ ] **Step 1: Replace all 4 system prompts**

Replace the `AGENT_CONFIGS` dict in `src/agentdb/agents/definitions.py` with:

```python
AGENT_CONFIGS: dict[str, AgentConfig] = {
    "mayor": AgentConfig(
        name="mayor",
        model="glm-5:cloud",
        system_prompt=(
            "You are the Mayor. You set strategic priorities for the city.\n\n"
            "Responsibilities:\n"
            "1. read_city_state to understand current conditions\n"
            "2. set_priority based on which failures are most critical\n"
            "3. assign_task when work needs to be routed\n\n"
            "Focus on the big picture: which services matter most, where to allocate effort.\n"
            "The orchestrator handles routine dispatch — you handle strategic decisions."
        ),
        tool_names=["read_city_state", "set_priority", "assign_task"],
        handoff_targets=["engineer", "monitor"],
    ),
    "engineer": AgentConfig(
        name="engineer",
        model="qwen3.5:cloud",
        system_prompt=(
            "You are a City Engineer. You write Python code for city services.\n"
            "Each service has a main.py with a handle_load(load, config) function:\n"
            "  Returns {'status': 'ok'|'degraded'|'failed', 'capacity': float, 'metrics': dict}\n\n"
            "Workflow (follow ALL steps in order):\n"
            "1. read_file to see current code and config.json\n"
            "2. Write improved code via deploy_staging\n"
            "3. run_tests to verify it compiles\n"
            "4. If tests pass: hand off to fixer to run hotfix_prod\n"
            "5. If tests fail: fix and retry from step 2\n\n"
            "CRITICAL: Code in staging does nothing until hotfix_prod merges it to production.\n"
            "Never skip steps. Write clean, efficient Python. Higher capacity handles more load."
        ),
        tool_names=["read_file", "write_file", "deploy_staging", "run_tests"],
        handoff_targets=["mayor", "fixer"],
    ),
    "monitor": AgentConfig(
        name="monitor",
        model="glm-5:cloud",
        system_prompt=(
            "You are the City Monitor. You watch service health and detect anomalies.\n\n"
            "Responsibilities:\n"
            "1. check_health to see all service statuses\n"
            "2. read_metrics for services showing issues\n"
            "3. create_incident for failures without existing incidents\n"
            "4. Hand off to fixer for service failures, mayor for strategic decisions\n\n"
            "Only create an incident if no open incident exists for that service.\n"
            "Include service name, load, capacity, and status in incident descriptions.\n"
            "Be concise. Report facts, not commentary."
        ),
        tool_names=["read_metrics", "check_health", "create_incident"],
        handoff_targets=["fixer", "mayor"],
    ),
    "fixer": AgentConfig(
        name="fixer",
        model="qwen3.5:cloud",
        system_prompt=(
            "You are the City Fixer. You diagnose and fix broken services.\n\n"
            "Workflow (follow ALL steps in order):\n"
            "1. read_file to see the failing service's code and config.json\n"
            "2. patch_file with the fix\n"
            "3. hotfix_prod to merge staging to production\n"
            "4. Hand off to monitor to verify resolution\n\n"
            "CRITICAL: Always call hotfix_prod after patching. Staged code does nothing until merged.\n"
            "If you can't fix it, rollback and escalate to mayor. Fix root causes, not symptoms."
        ),
        tool_names=["read_file", "patch_file", "hotfix_prod", "rollback"],
        handoff_targets=["monitor", "mayor"],
    ),
}
```

- [ ] **Step 2: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All pass — prompts are just strings, no test depends on their content

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/agents/definitions.py
git commit -m "feat: update agent prompts with explicit deploy workflow checklists"
```

---

## Chunk 2: Orchestrator + Wiring (Tasks 4-9)

### Task 4: Add _triage() method to AgentRunner

**Files:**
- Modify: `src/agentdb/agents/runner.py`
- Test: `tests/test_runner.py` (add tests)

The triage method reads KV state and FS to identify what needs attention. It returns a structured summary dict. The runner needs new constructor params: `kv`, `fs`, `city_tools`.

- [ ] **Step 1: Write failing tests for _triage()**

Add to `tests/test_runner.py`:

```python
def _make_runner_with_state(db):
    """Helper to create a runner with real KV/FS for triage testing."""
    from agentdb.db.filesystem import VirtualFS
    from agentdb.db.kvstore import KVStore
    from agentdb.agents.tools import CityTools
    from agentdb.db.overlay import OverlayFS

    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    city_tools = CityTools(fs=fs, kv=kv, overlay=overlay)
    broadcaster = MagicMock()
    broadcaster.broadcast = AsyncMock()
    engine = MagicMock()
    engine.tick = 10
    runner = AgentRunner(
        swarm=None,
        broadcaster=broadcaster,
        engine=engine,
        event_buffer=[],
        agent_names=["mayor", "engineer", "monitor", "fixer"],
        kv=kv,
        fs=fs,
        city_tools=city_tools,
    )
    return runner, kv, fs


def test_triage_all_ok(db):
    """Triage should return no actions when all services are ok."""
    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    result = runner._triage()
    assert result["needs_action"] is False
    assert len(result["failed"]) == 0
    assert len(result["degraded"]) == 0


def test_triage_detects_failed_services(db):
    """Triage should identify failed services."""
    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    kv.set("service:power-grid:status", "failed")
    kv.set("service:power-grid:capacity", "0.0")
    result = runner._triage()
    assert result["needs_action"] is True
    assert "power-grid" in result["failed"]


def test_triage_detects_degraded_services(db):
    """Triage should identify degraded services."""
    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    kv.set("service:water-system:status", "degraded")
    result = runner._triage()
    assert result["needs_action"] is True
    assert "water-system" in result["degraded"]


def test_triage_ignores_stale_incidents(db):
    """Triage should ignore incidents created more than 10 ticks ago."""
    import json
    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    # Create a stale incident (tick 0, current tick is 10 → stale)
    runner._engine.tick = 10
    fs.write_file("/city/incidents/INC-001.json", json.dumps({
        "id": "INC-001", "service": "power-grid", "severity": "high",
        "status": "open", "created_at": 0,
    }))
    result = runner._triage()
    assert result["needs_action"] is False
    assert len(result["recent_incidents"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_runner.py::test_triage_all_ok tests/test_runner.py::test_triage_detects_failed_services tests/test_runner.py::test_triage_detects_degraded_services tests/test_runner.py::test_triage_ignores_stale_incidents -v`
Expected: FAIL — `AgentRunner.__init__` doesn't accept `kv`, `fs`, `city_tools`; `_triage()` doesn't exist

- [ ] **Step 3: Implement _triage() and update AgentRunner.__init__**

In `src/agentdb/agents/runner.py`, update imports:
```python
from __future__ import annotations

import json
import time
import traceback

from langchain_core.messages import AIMessage, HumanMessage

from agentdb.dashboard.broadcast import Broadcaster
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.simulation.engine import SimulationEngine
```

Update `__init__` to accept new params (add after existing params, before `thread_id`):
```python
def __init__(
    self,
    swarm,
    broadcaster: Broadcaster,
    engine: SimulationEngine,
    event_buffer: list,
    agent_names: list[str],
    kv: KVStore | None = None,
    fs: VirtualFS | None = None,
    city_tools=None,
    thread_id: str = "city-sim",
):
    self._swarm = swarm
    self._broadcaster = broadcaster
    self._engine = engine
    self._event_buffer = event_buffer
    self._agent_names = agent_names
    self._kv = kv
    self._fs = fs
    self._city_tools = city_tools
    self._thread_id = thread_id
    self._cycle_counter = 0
    self._last_plan: dict | None = None
    self._last_results: dict | None = None
```

Add `_triage()` method after `_extract_service`:
```python
def _triage(self) -> dict:
    """Deterministic triage: inspect KV state and FS for actionable work."""
    failed = []
    degraded = []
    services = {}

    if self._kv is not None:
        service_keys = self._kv.list_prefix("service:")
        service_names = sorted({k.split(":")[1] for k, _ in service_keys})
        for svc in service_names:
            status = self._kv.get(f"service:{svc}:status", "ok")
            load = self._kv.get(f"service:{svc}:load", "0.5")
            capacity = self._kv.get(f"service:{svc}:capacity", "1.0")
            services[svc] = {"status": status, "load": load, "capacity": capacity}
            if status == "failed":
                failed.append(svc)
            elif status == "degraded":
                degraded.append(svc)

    # Scan recent incidents (ignore stale ones > 60 seconds old)
    # Incidents store created_at as unix timestamp via int(time.time())
    recent_incidents = []
    if self._fs is not None:
        incident_names = self._fs.list_dir("/city/incidents")
        for name in incident_names:
            content = self._fs.read_file(f"/city/incidents/{name}")
            if content is None:
                continue
            try:
                inc = json.loads(content)
            except json.JSONDecodeError:
                continue
            created_at = inc.get("created_at", 0)
            age_seconds = time.time() - created_at
            if age_seconds <= 60:
                recent_incidents.append(inc)

    needs_action = len(failed) > 0 or len(degraded) > 0 or len(recent_incidents) > 0

    return {
        "needs_action": needs_action,
        "failed": failed,
        "degraded": degraded,
        "services": services,
        "recent_incidents": recent_incidents,
        "tick": self._engine.tick,
    }
```

Note: `import time` must be added to the runner.py imports.
```python
def test_triage_ignores_stale_incidents(db):
    """Triage should ignore incidents older than 60 seconds."""
    import json
    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    # Create a stale incident (created_at=0 → epoch 1970 → definitely stale)
    fs.write_file("/city/incidents/INC-001.json", json.dumps({
        "id": "INC-001", "service": "power-grid", "severity": "high",
        "status": "open", "created_at": 0,
    }))
    result = runner._triage()
    assert result["needs_action"] is False
    assert len(result["recent_incidents"]) == 0


def test_triage_finds_recent_incidents(db):
    """Triage should include incidents created within the last 60 seconds."""
    import json
    import time as _time
    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    # Create a recent incident
    fs.write_file("/city/incidents/INC-002.json", json.dumps({
        "id": "INC-002", "service": "water-system", "severity": "high",
        "status": "open", "created_at": int(_time.time()),
    }))
    result = runner._triage()
    assert result["needs_action"] is True
    assert len(result["recent_incidents"]) == 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_runner.py -v`
Expected: All pass (new triage tests + existing tests — existing tests use defaults `kv=None`, `fs=None`, `city_tools=None`)

- [ ] **Step 5: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/agents/runner.py tests/test_runner.py
git commit -m "feat: add _triage() method and new constructor params to AgentRunner"
```

---

### Task 5: Add _plan() method to AgentRunner

**Files:**
- Modify: `src/agentdb/agents/runner.py`
- Test: `tests/test_runner.py` (add tests)

- [ ] **Step 1: Write failing tests for _plan()**

Add to `tests/test_runner.py`:

```python
def test_plan_parses_valid_json():
    """_parse_plan should extract tasks from valid planner JSON."""
    from agentdb.agents.runner import AgentRunner
    raw = '{"tasks": [{"agent": "fixer", "instruction": "Fix power-grid"}]}'
    tasks = AgentRunner._parse_plan(raw)
    assert len(tasks) == 1
    assert tasks[0]["agent"] == "fixer"
    assert tasks[0]["instruction"] == "Fix power-grid"


def test_plan_returns_empty_on_malformed_json():
    """_parse_plan should return empty list on malformed JSON."""
    from agentdb.agents.runner import AgentRunner
    assert AgentRunner._parse_plan("not json at all") == []
    assert AgentRunner._parse_plan('{"tasks": "wrong type"}') == []
    assert AgentRunner._parse_plan('{"no_tasks_key": []}') == []


def test_plan_extracts_json_from_markdown():
    """_parse_plan should handle JSON wrapped in markdown code fences."""
    from agentdb.agents.runner import AgentRunner
    raw = '```json\n{"tasks": [{"agent": "monitor", "instruction": "Create incident"}]}\n```'
    tasks = AgentRunner._parse_plan(raw)
    assert len(tasks) == 1
    assert tasks[0]["agent"] == "monitor"


async def test_plan_returns_empty_on_llm_failure(mock_broadcaster, mock_engine):
    """_plan() should return empty list when LLM call fails."""
    from unittest.mock import patch
    runner = AgentRunner(
        swarm=None,
        broadcaster=mock_broadcaster,
        engine=mock_engine,
        event_buffer=[],
        agent_names=["monitor"],
    )
    triage = {"needs_action": True, "failed": ["power-grid"], "degraded": [],
              "services": {}, "recent_incidents": [], "tick": 5}
    with patch("agentdb.agents.runner.ChatOllama", side_effect=Exception("connection refused")):
        tasks = await runner._plan(triage)
    assert tasks == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_runner.py::test_plan_parses_valid_json tests/test_runner.py::test_plan_returns_empty_on_malformed_json tests/test_runner.py::test_plan_extracts_json_from_markdown -v`
Expected: FAIL — `_parse_plan` doesn't exist

- [ ] **Step 3: Implement _parse_plan and _plan()**

Add to `src/agentdb/agents/runner.py` imports:
```python
import re
```

Add the planner prompt as a module-level constant after imports:
```python
PLANNER_PROMPT = """\
You are the city operations planner. Given the current city state, decide which agents to dispatch and what each should do.

Rules:
- Only dispatch agents when there's actionable work
- Fixer handles failed services (must complete: read → patch → hotfix_prod)
- Engineer handles degraded services or capacity improvements (must complete: read → deploy_staging → run_tests → hand off to fixer for hotfix)
- Monitor creates incidents for untracked failures
- Mayor sets priorities when multiple services need attention
- Never dispatch an agent without a specific instruction

Current state:
{triage_summary}

Previous cycle results:
{last_plan_results}

Respond with JSON only: {{"tasks": [{{"agent": "...", "instruction": "..."}}]}}"""
```

Add `_parse_plan` as a static method:
```python
@staticmethod
def _parse_plan(raw: str) -> list[dict]:
    """Parse planner LLM output into a list of task dicts."""
    # Strip markdown code fences if present
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if match:
        raw = match.group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return []
    return tasks
```

Add `_plan()` async method:
```python
async def _plan(self, triage: dict) -> list[dict]:
    """Call LLM planner to generate targeted agent tasks."""
    try:
        from langchain_ollama import ChatOllama
        planner_llm = ChatOllama(model="glm-5:cloud")

        triage_summary = json.dumps(triage, indent=2)
        last_results = json.dumps(self._last_results or {}, indent=2)
        prompt = PLANNER_PROMPT.format(
            triage_summary=triage_summary,
            last_plan_results=last_results,
        )

        response = await planner_llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        tasks = self._parse_plan(content)
        if tasks:
            return tasks
    except Exception as exc:
        print(f"[tick {self._engine.tick}] Planner error: {exc}")

    # Fallback: return empty (caller will use generic prompt)
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_runner.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/agents/runner.py tests/test_runner.py
git commit -m "feat: add _plan() and _parse_plan() for LLM planner in AgentRunner"
```

---

### Task 6: Rewrite run_cycle() with three-phase orchestration

**Files:**
- Modify: `src/agentdb/agents/runner.py`

This is the integration task — wire triage → plan → dispatch into `run_cycle()`. The existing `_process_messages`, `_flush_event_buffer`, and `_broadcast_agent_statuses` methods are reused. `_invoke_swarm` is no longer needed (inlined into `_dispatch_generic` with fresh thread IDs).

- [ ] **Step 1: Rewrite run_cycle() and add _dispatch()**

Replace the existing `run_cycle()` method with:
```python
async def run_cycle(self) -> None:
    """Run one orchestration cycle: triage → plan → dispatch."""
    if self._swarm is None:
        await self._broadcast_idle_all()
        return

    # Phase 1: Deterministic triage
    triage = self._triage()
    if not triage["needs_action"]:
        await self._broadcast_idle_all()
        return

    # Phase 2: LLM planner
    planned_tasks = await self._plan(triage)

    # Phase 3: Dispatch
    if planned_tasks:
        await self._dispatch_planned(planned_tasks)
    else:
        # Fallback: generic prompt (planner failed or returned empty)
        await self._dispatch_generic()

async def _dispatch_planned(self, tasks: list[dict]) -> None:
    """Dispatch agents with targeted instructions from the planner."""
    self._cycle_counter += 1
    all_participated: dict[str, str] = {}

    for i, task in enumerate(tasks):
        agent_name = task.get("agent", "")
        instruction = task.get("instruction", "")
        if not agent_name or not instruction:
            continue

        # Set agent attribution for the entry-point agent.
        # Known limitation: if the swarm hands off to another agent within
        # this ainvoke, tool calls by the second agent will be attributed to
        # the entry-point agent. This is acceptable for Phase 1.
        if self._city_tools is not None:
            self._city_tools.set_current_agent(agent_name)

        await self._broadcaster.broadcast("agent_update", {
            "agent": agent_name, "status": "working",
            "message": instruction[:200],
            "tick": self._engine.tick,
        })

        try:
            thread_id = f"cycle-{self._cycle_counter}-{i}"
            prompt = f"Tick {self._engine.tick}. {instruction}"
            result = await self._swarm.ainvoke(
                {"messages": [HumanMessage(content=prompt)]},
                config={"configurable": {"thread_id": thread_id}},
            )
            participated = await self._process_messages(result)
            all_participated.update(participated)
        except Exception as exc:
            print(f"[tick {self._engine.tick}] Dispatch error ({agent_name}): {exc}")
            await self._broadcaster.broadcast("agent_update", {
                "agent": agent_name, "status": "error",
                "message": str(exc)[:200], "tick": self._engine.tick,
            })

    # Clear agent attribution and drain audit IDs
    if self._city_tools is not None:
        self._city_tools.pop_audit_ids()
        self._city_tools.set_current_agent(None)

    await self._flush_event_buffer()
    await self._broadcast_agent_statuses(all_participated)

    # Track results for next cycle's planner
    self._last_plan = {"tasks": tasks}
    self._last_results = {
        "participated": list(all_participated.keys()),
        "tick": self._engine.tick,
    }
    print(f"[tick {self._engine.tick}] Planned: {len(tasks)} tasks, "
          f"Agents: {', '.join(all_participated.keys()) or 'none'}")

async def _dispatch_generic(self) -> None:
    """Fallback: dispatch all agents with the original generic prompt."""
    self._cycle_counter += 1
    for name in self._agent_names:
        await self._broadcaster.broadcast("agent_update", {
            "agent": name, "status": "working",
            "message": f"Checking city health (tick {self._engine.tick})...",
            "tick": self._engine.tick,
        })

    try:
        # Use fresh thread ID to prevent unbounded conversation history
        thread_id = f"cycle-{self._cycle_counter}-generic"
        prompt = (
            f"Tick {self._engine.tick}. Check city health. "
            "If any service is degraded or failed, create an incident "
            "and hand off to the appropriate agent. Otherwise report status."
        )
        result = await self._swarm.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": thread_id}},
        )
        participated = await self._process_messages(result)
        await self._flush_event_buffer()
        await self._broadcast_agent_statuses(participated)
        print(f"[tick {self._engine.tick}] Generic dispatch. "
              f"Agents: {', '.join(participated.keys()) or 'none'}")
    except Exception as exc:
        print(f"[tick {self._engine.tick}] Agent error: {exc}")
        traceback.print_exc()
        self._event_buffer.clear()
        for name in self._agent_names:
            await self._broadcaster.broadcast("agent_update", {
                "agent": name, "status": "error",
                "message": str(exc)[:200], "tick": self._engine.tick,
            })
```

- [ ] **Step 2: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All pass — existing `test_runner_no_swarm` still works (swarm=None → idle). The new params default to `None` so existing test constructors are unaffected.

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/agents/runner.py
git commit -m "feat: rewrite run_cycle with 3-phase orchestration (triage, plan, dispatch)"
```

---

### Task 7: Return city_tools from build_swarm

**Files:**
- Modify: `src/agentdb/agents/swarm.py:40-65`

This task is paired with Task 8 (main.py wiring) — both must be applied together since changing the return type of `build_swarm` without updating `main.py` would break the app.

- [ ] **Step 1: Modify build_swarm to return tuple**

In `src/agentdb/agents/swarm.py`, change line 65 from:
```python
return workflow.compile(checkpointer=checkpointer)
```
to:
```python
return workflow.compile(checkpointer=checkpointer), city_tools
```

- [ ] **Step 2: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All pass — nothing in tests calls `build_swarm` directly (it requires Ollama)

- [ ] **Step 3: Do NOT commit yet — proceed to Task 8 and commit both together**

---

### Task 8: Update main.py wiring

**Files:**
- Modify: `main.py:113-129`

- [ ] **Step 1: Update build_swarm unpacking and AgentRunner construction**

In `main.py`, replace lines 113-129:

```python
    try:
        from agentdb.agents.swarm import build_swarm
        swarm = build_swarm(fs, kv, overlay, event_buffer=event_buffer, audit=audit)
        print("Agent swarm initialized.")
    except Exception as exc:  # noqa: BLE001
        swarm = None
        print(f"Agent swarm unavailable ({exc}); running without agents.")

    # 8. Agent runner
    all_agent_names = list(AGENT_CONFIGS.keys())
    runner = AgentRunner(
        swarm=swarm,
        broadcaster=broadcaster,
        engine=engine,
        event_buffer=event_buffer,
        agent_names=all_agent_names,
    )
```

with:

```python
    city_tools = None
    try:
        from agentdb.agents.swarm import build_swarm
        swarm, city_tools = build_swarm(fs, kv, overlay, event_buffer=event_buffer, audit=audit)
        print("Agent swarm initialized.")
    except Exception as exc:  # noqa: BLE001
        swarm = None
        print(f"Agent swarm unavailable ({exc}); running without agents.")

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
```

- [ ] **Step 2: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/agents/swarm.py main.py
git commit -m "feat: return city_tools from build_swarm and wire into AgentRunner"
```

---

### Task 9: Integration verification

- [ ] **Step 1: Run full test suite**

Run: `uv run python -m pytest -v`
Expected: All pass

- [ ] **Step 2: Delete stale database and start fresh**

```bash
rm -f city.db
```

- [ ] **Step 3: Start the application**

```bash
uv run python main.py
```

Expected output should include:
- `Agent swarm initialized.`
- After first tick: `[tick N] Planned: X tasks, Agents: ...` (planned dispatch) or `[tick N] Generic dispatch.` (if planner fails)

- [ ] **Step 4: Verify in dashboard**

Open http://localhost:8000 and check:
- Services start ok, then some degrade/fail based on load
- Chip bar shows agent activity with agent names
- Graph shows agent presence dots when agents are working
- Agents should be calling `hotfix_prod` after patching (visible in chip bar as code_diff merge events)

- [ ] **Step 5: Check audit log for agent attribution**

```bash
curl -s 'http://localhost:8000/api/audit?limit=10' | python3 -m json.tool
```

Expected: `agent_name` field should be populated (not null) for tool calls made by agents

- [ ] **Step 6: Commit any fixes discovered during verification**

If issues found, fix and commit with descriptive messages.
