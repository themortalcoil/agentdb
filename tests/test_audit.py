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
