import json
import pytest
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
    with pytest.raises(ValueError, match="under /city/"):
        city_tools.write_file("/etc/passwd", "hack")


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
