import json
import pytest
from agentdb.db.audit import AuditLog
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS
from agentdb.agents.tools import CityTools


@pytest.fixture
def city_tools(db):
    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    return CityTools(fs=fs, kv=kv, overlay=overlay)


def test_read_city_state(city_tools):
    city_tools.kv.set("city:population", "10000")
    city_tools.kv.set("service:power-grid:status", "ok")
    result = city_tools.read_city_state()
    state = json.loads(result)
    assert "city:population" in str(state)


def test_write_file_validates_path(city_tools):
    result = city_tools.write_file("/etc/passwd", "hack")
    assert "ERROR" in result
    assert "/city/" in result


def test_write_and_read_file(city_tools):
    city_tools.write_file("/city/services/power-grid/main.py", "print('hello')")
    content = city_tools.read_file("/city/services/power-grid/main.py")
    assert content == "print('hello')"


def test_deploy_staging(city_tools):
    city_tools.deploy_staging(
        "/city/services/power-grid/main.py", "staged code"
    )
    assert (
        city_tools.overlay.read_file("/city/services/power-grid/main.py")
        == "staged code"
    )


def test_read_metrics(city_tools):
    city_tools.kv.set("service:power-grid:status", "ok")
    city_tools.kv.set("service:power-grid:load", "0.75")
    result = city_tools.read_metrics("power-grid")
    metrics = json.loads(result)
    assert metrics["status"] == "ok"
    assert metrics["load"] == "0.75"


def test_create_incident(city_tools):
    result = city_tools.create_incident(
        service="power-grid",
        description="Power grid is failing under load",
        severity="high",
    )
    assert "INC-" in result
    content = city_tools.fs.read_file(f"/city/incidents/{result}.json")
    assert content is not None


def test_set_priority(city_tools):
    city_tools.set_priority("reliability")
    assert city_tools.kv.get("mayor:priority") == "reliability"


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


def test_set_current_agent_flows_to_audit(db):
    """set_current_agent should cause audit rows to record agent_name."""
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
