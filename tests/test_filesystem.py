from agentdb.db.filesystem import VirtualFS


def test_write_and_read_file(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "print('hello')")
    content = fs.read_file("/city/services/power-grid/main.py")
    assert content == "print('hello')"


def test_read_nonexistent_returns_none(db):
    fs = VirtualFS(db)
    assert fs.read_file("/does/not/exist") is None


def test_overwrite_file(db):
    fs = VirtualFS(db)
    fs.write_file("/city/test.py", "v1")
    fs.write_file("/city/test.py", "v2")
    assert fs.read_file("/city/test.py") == "v2"


def test_delete_file(db):
    fs = VirtualFS(db)
    fs.write_file("/city/test.py", "content")
    fs.delete("/city/test.py")
    assert fs.read_file("/city/test.py") is None


def test_list_directory(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "code")
    fs.write_file("/city/services/power-grid/config.json", "{}")
    entries = fs.list_dir("/city/services/power-grid")
    assert set(entries) == {"main.py", "config.json"}


def test_list_root(db):
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "code")
    fs.write_file("/city/plans/TASK-001.md", "plan")
    entries = fs.list_dir("/city")
    assert "services" in entries
    assert "plans" in entries


def test_list_empty_dir(db):
    fs = VirtualFS(db)
    entries = fs.list_dir("/nonexistent")
    assert entries == []


def test_exists(db):
    fs = VirtualFS(db)
    fs.write_file("/city/test.py", "content")
    assert fs.exists("/city/test.py") is True
    assert fs.exists("/city/nope.py") is False
