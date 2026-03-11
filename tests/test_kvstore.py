from agentdb.db.kvstore import KVStore


def test_set_and_get(db):
    kv = KVStore(db)
    kv.set("city:population", "12500")
    assert kv.get("city:population") == "12500"


def test_get_missing_returns_none(db):
    kv = KVStore(db)
    assert kv.get("nonexistent") is None


def test_get_missing_with_default(db):
    kv = KVStore(db)
    assert kv.get("nonexistent", "fallback") == "fallback"


def test_set_overwrites(db):
    kv = KVStore(db)
    kv.set("key", "old")
    kv.set("key", "new")
    assert kv.get("key") == "new"


def test_delete(db):
    kv = KVStore(db)
    kv.set("key", "value")
    kv.delete("key")
    assert kv.get("key") is None


def test_list_by_prefix(db):
    kv = KVStore(db)
    kv.set("service:power:status", "ok")
    kv.set("service:water:status", "degraded")
    kv.set("agent:mayor:energy", "100")
    results = kv.list_prefix("service:")
    assert len(results) == 2
    assert all(k.startswith("service:") for k, _ in results)


def test_set_many(db):
    kv = KVStore(db)
    kv.set_many({"a": "1", "b": "2", "c": "3"})
    assert kv.get("a") == "1"
    assert kv.get("b") == "2"
    assert kv.get("c") == "3"
