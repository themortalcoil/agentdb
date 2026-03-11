import pytest
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.overlay import OverlayFS
from agentdb.agents.tools import CityTools


@pytest.fixture
def event_buffer():
    return []


@pytest.fixture
def city_tools(db, event_buffer):
    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    return CityTools(fs=fs, kv=kv, overlay=overlay, event_buffer=event_buffer)


def test_write_file_emits_code_diff(city_tools, event_buffer):
    """write_file should capture old content and emit code_diff + fs_change."""
    city_tools.fs.write_file("/city/services/power-grid/main.py", "old code")
    event_buffer.clear()

    city_tools.write_file("/city/services/power-grid/main.py", "new code")

    diffs = [e for e in event_buffer if e["type"] == "code_diff"]
    assert len(diffs) == 1
    assert diffs[0]["path"] == "/city/services/power-grid/main.py"
    assert diffs[0]["old_content"] == "old code"
    assert diffs[0]["new_content"] == "new code"
    assert diffs[0]["action"] == "write"


def test_write_file_emits_fs_change(city_tools, event_buffer):
    city_tools.write_file("/city/services/power-grid/main.py", "content")

    changes = [e for e in event_buffer if e["type"] == "fs_change"]
    assert len(changes) == 1
    assert changes[0]["path"] == "/city/services/power-grid/main.py"
    assert changes[0]["action"] == "write"
    assert changes[0]["size"] == len("content")


def test_write_new_file_has_none_old_content(city_tools, event_buffer):
    """Writing a new file should have old_content=None."""
    city_tools.write_file("/city/services/power-grid/main.py", "new code")

    diffs = [e for e in event_buffer if e["type"] == "code_diff"]
    assert diffs[0]["old_content"] is None


def test_deploy_staging_emits_staged_diff(city_tools, event_buffer):
    city_tools.fs.write_file("/city/services/power-grid/main.py", "prod code")
    event_buffer.clear()

    city_tools.deploy_staging("/city/services/power-grid/main.py", "staged code")

    diffs = [e for e in event_buffer if e["type"] == "code_diff"]
    assert len(diffs) == 1
    assert diffs[0]["old_content"] == "prod code"
    assert diffs[0]["new_content"] == "staged code"
    assert diffs[0]["action"] == "stage"


def test_patch_file_emits_staged_diff(city_tools, event_buffer):
    city_tools.fs.write_file("/city/services/power-grid/main.py", "prod code")
    event_buffer.clear()

    city_tools.patch_file("/city/services/power-grid/main.py", "patched code")

    diffs = [e for e in event_buffer if e["type"] == "code_diff"]
    assert len(diffs) == 1
    assert diffs[0]["old_content"] == "prod code"
    assert diffs[0]["new_content"] == "patched code"
    assert diffs[0]["action"] == "stage"


def test_hotfix_prod_emits_merge_diff(city_tools, event_buffer):
    city_tools.fs.write_file("/city/services/power-grid/main.py", "old prod")
    city_tools.overlay.write_file("/city/services/power-grid/main.py", "fixed")
    event_buffer.clear()

    city_tools.hotfix_prod("power-grid")

    diffs = [e for e in event_buffer if e["type"] == "code_diff"]
    assert len(diffs) >= 1
    merge_diff = diffs[0]
    assert merge_diff["action"] == "merge"
    assert merge_diff["new_content"] == "fixed"


def test_rollback_emits_fs_change_delete(city_tools, event_buffer):
    city_tools.overlay.write_file("/city/services/power-grid/main.py", "staged")
    event_buffer.clear()

    city_tools.rollback("power-grid")

    changes = [e for e in event_buffer if e["type"] == "fs_change"]
    assert len(changes) >= 1
    assert changes[0]["action"] == "delete"


def test_create_incident_emits_fs_change(city_tools, event_buffer):
    inc_id = city_tools.create_incident(
        service="power-grid", description="Overloaded", severity="high"
    )

    changes = [e for e in event_buffer if e["type"] == "fs_change"]
    assert len(changes) == 1
    assert f"/city/incidents/{inc_id}.json" == changes[0]["path"]


def test_assign_task_emits_fs_change(city_tools, event_buffer):
    city_tools.assign_task("power-grid", "Fix capacity", "engineer")

    changes = [e for e in event_buffer if e["type"] == "fs_change"]
    assert len(changes) == 1
    assert "/city/plans/" in changes[0]["path"]


def test_no_buffer_still_works(db):
    """CityTools without event_buffer should work normally (no crash)."""
    fs = VirtualFS(db)
    kv = KVStore(db)
    overlay = OverlayFS(db, fs)
    tools = CityTools(fs=fs, kv=kv, overlay=overlay)
    tools.write_file("/city/test.py", "code")
    assert tools.read_file("/city/test.py") == "code"
