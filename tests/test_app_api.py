import pytest
from fastapi.testclient import TestClient
from agentdb.db.filesystem import VirtualFS
from agentdb.db.schema import init_db
from agentdb.dashboard.broadcast import Broadcaster
from agentdb.dashboard.app import create_app, build_fs_tree
import sqlite3


@pytest.fixture
def app_fixtures():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    fs = VirtualFS(conn)
    broadcaster = Broadcaster()
    app = create_app(broadcaster, engine=None, fs=fs)
    client = TestClient(app)
    return client, fs, conn


def test_api_file_returns_content(app_fixtures):
    client, fs, _ = app_fixtures
    fs.write_file("/city/services/power-grid/main.py", "print('hello')")

    resp = client.get("/api/file", params={"path": "/city/services/power-grid/main.py"})
    assert resp.status_code == 200
    assert resp.text == "print('hello')"
    assert "text/plain" in resp.headers["content-type"]


def test_api_file_404_missing(app_fixtures):
    client, _, _ = app_fixtures

    resp = client.get("/api/file", params={"path": "/city/services/nonexistent.py"})
    assert resp.status_code == 404


def test_api_file_400_bad_path(app_fixtures):
    client, _, _ = app_fixtures

    resp = client.get("/api/file", params={"path": "/etc/passwd"})
    assert resp.status_code == 400


def test_api_file_400_path_traversal(app_fixtures):
    client, _, _ = app_fixtures

    resp = client.get("/api/file", params={"path": "/city/../../etc/passwd"})
    assert resp.status_code == 400


def test_build_fs_tree(app_fixtures):
    _, fs, _ = app_fixtures
    fs.write_file("/city/services/power-grid/main.py", "code here")
    fs.write_file("/city/services/power-grid/config.json", '{"cap": 1}')
    fs.write_file("/city/incidents/INC-001.json", '{"id": "INC-001"}')

    tree = build_fs_tree(fs)

    # tree should be nested dict. Files are ints, dirs are dicts.
    assert isinstance(tree["city"], dict)
    assert isinstance(tree["city"]["services"], dict)
    assert isinstance(tree["city"]["services"]["power-grid"], dict)
    assert isinstance(tree["city"]["services"]["power-grid"]["main.py"], int)
    assert tree["city"]["services"]["power-grid"]["main.py"] == len("code here")
    assert isinstance(tree["city"]["incidents"], dict)
    assert isinstance(tree["city"]["incidents"]["INC-001.json"], int)
