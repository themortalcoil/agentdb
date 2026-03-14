import threading
import time
from agentdb.db.audit import AuditLog


def test_log_and_query(db):
    audit = AuditLog(db)
    audit.log("write_file", '{"path": "/city/services/power-grid/main.py"}', '"ok"')
    results = audit.query()
    assert len(results) == 1
    assert results[0]["name"] == "write_file"


def test_log_records_timing(db):
    audit = AuditLog(db)
    audit.log("slow_tool", "{}", '"done"')
    results = audit.query()
    assert results[0]["duration_ms"] >= 0
    assert results[0]["started_at"] > 0
    assert results[0]["completed_at"] >= results[0]["started_at"]


def test_log_error(db):
    audit = AuditLog(db)
    audit.log("bad_tool", "{}", None, error="something broke")
    results = audit.query()
    assert results[0]["error"] == "something broke"
    assert results[0]["result"] is None


def test_query_by_name(db):
    audit = AuditLog(db)
    audit.log("write_file", "{}", '"ok"')
    audit.log("read_file", "{}", '"data"')
    audit.log("write_file", "{}", '"ok"')
    results = audit.query(name="write_file")
    assert len(results) == 2


def test_query_limit(db):
    audit = AuditLog(db)
    for i in range(10):
        audit.log("tool", "{}", f'"{i}"')
    results = audit.query(limit=3)
    assert len(results) == 3


def test_context_manager(db):
    audit = AuditLog(db)
    with audit.track("my_tool", '{"arg": 1}') as tracker:
        tracker.result = '"computed"'
    results = audit.query()
    assert len(results) == 1
    assert results[0]["name"] == "my_tool"
    assert results[0]["result"] == '"computed"'


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
