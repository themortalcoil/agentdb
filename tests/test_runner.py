import pytest
from unittest.mock import AsyncMock, MagicMock
from agentdb.agents.runner import AgentRunner


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
    # Check that idle was broadcast for all 4 agents
    idle_calls = [
        c
        for c in mock_broadcaster.broadcast.call_args_list
        if c[0][0] == "agent_update" and c[0][1].get("status") == "idle"
    ]
    assert len(idle_calls) == 4


async def test_runner_cycle_counter_starts_at_zero(mock_broadcaster, mock_engine):
    runner = AgentRunner(
        swarm=None,
        broadcaster=mock_broadcaster,
        engine=mock_engine,
        event_buffer=[],
        agent_names=["monitor"],
    )
    assert runner._cycle_counter == 0


async def test_extract_service_from_tool_calls():
    """AgentRunner._extract_service should find service names in tool args."""
    from agentdb.agents.runner import AgentRunner

    # Test path-based extraction
    assert (
        AgentRunner._extract_service(
            [{"name": "read_file", "args": {"path": "/city/services/power-grid/main.py"}}]
        )
        == "power-grid"
    )
    # Test direct service argument
    assert (
        AgentRunner._extract_service(
            [
                {
                    "name": "create_incident",
                    "args": {"service": "water-system", "description": "down"},
                }
            ]
        )
        == "water-system"
    )
    # Test no service extractable
    assert AgentRunner._extract_service([{"name": "read_city_state", "args": {}}]) is None
    # Test empty tool calls
    assert AgentRunner._extract_service([]) is None


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
    """Triage should ignore incidents older than 60 seconds."""
    import json as _json

    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    # Create a stale incident (created_at=0 → epoch 1970 → definitely stale)
    fs.write_file(
        "/city/incidents/INC-001.json",
        _json.dumps(
            {
                "id": "INC-001",
                "service": "power-grid",
                "severity": "high",
                "status": "open",
                "created_at": 0,
            }
        ),
    )
    result = runner._triage()
    assert result["needs_action"] is False
    assert len(result["recent_incidents"]) == 0


def test_triage_finds_recent_incidents(db):
    """Triage should include incidents created within the last 60 seconds."""
    import json as _json
    import time as _time

    runner, kv, fs = _make_runner_with_state(db)
    for svc in ["power-grid", "water-system", "traffic-control", "comms-network"]:
        kv.set(f"service:{svc}:status", "ok")
        kv.set(f"service:{svc}:load", "0.5")
        kv.set(f"service:{svc}:capacity", "1.0")
    # Create a recent incident
    fs.write_file(
        "/city/incidents/INC-002.json",
        _json.dumps(
            {
                "id": "INC-002",
                "service": "water-system",
                "severity": "high",
                "status": "open",
                "created_at": int(_time.time()),
            }
        ),
    )
    result = runner._triage()
    assert result["needs_action"] is True
    assert len(result["recent_incidents"]) == 1


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
    triage = {
        "needs_action": True,
        "failed": ["power-grid"],
        "degraded": [],
        "services": {},
        "recent_incidents": [],
        "tick": 5,
    }
    with patch("langchain_ollama.ChatOllama", side_effect=Exception("connection refused")):
        tasks = await runner._plan(triage)
    assert tasks == []
