from agentdb.db.filesystem import VirtualFS
from agentdb.db.overlay import OverlayFS


def test_read_through_to_base(db):
    """Overlay reads fall through to base when no overlay file exists."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    assert overlay.read_file("/city/services/power-grid/main.py") == "base code"


def test_overlay_write_shadows_base(db):
    """Writing to overlay shadows the base file."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "staged code")
    assert overlay.read_file("/city/services/power-grid/main.py") == "staged code"
    assert fs.read_file("/city/services/power-grid/main.py") == "base code"


def test_overlay_delete_creates_whiteout(db):
    """Deleting in overlay masks the base file without removing it."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.delete_file("/city/services/power-grid/main.py")
    assert overlay.read_file("/city/services/power-grid/main.py") is None
    assert fs.read_file("/city/services/power-grid/main.py") == "base code"


def test_merge_overlay_to_base(db):
    """Merging applies overlay changes to the base filesystem."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "staged code")
    overlay.merge()
    assert fs.read_file("/city/services/power-grid/main.py") == "staged code"


def test_merge_applies_whiteouts(db):
    """Merging deletes base files that have whiteout entries."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/old.py", "dead code")
    overlay = OverlayFS(db, fs)
    overlay.delete_file("/city/services/power-grid/old.py")
    overlay.merge()
    assert fs.read_file("/city/services/power-grid/old.py") is None


def test_discard_overlay(db):
    """Discarding overlay removes all staged changes."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base code")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "staged code")
    overlay.discard()
    assert overlay.read_file("/city/services/power-grid/main.py") == "base code"


def test_list_changes(db):
    """List all files modified or deleted in the overlay."""
    fs = VirtualFS(db)
    fs.write_file("/city/services/power-grid/main.py", "base")
    fs.write_file("/city/services/power-grid/config.json", "{}")
    overlay = OverlayFS(db, fs)
    overlay.write_file("/city/services/power-grid/main.py", "new code")
    overlay.delete_file("/city/services/power-grid/config.json")
    changes = overlay.list_changes()
    assert len(changes) == 2
    by_type = {c.change_type: c for c in changes}
    assert by_type["modified"].path == "/city/services/power-grid/main.py"
    assert by_type["deleted"].path == "/city/services/power-grid/config.json"
