# Agent Visibility Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface agent conversations, code diffs, and filesystem changes in the dashboard via a tabbed detail panel.

**Architecture:** CityTools buffers file-change events during each swarm cycle. After the cycle, `run_agents()` walks the LangGraph message history to extract agent conversations, enriches the buffered events with agent attribution, and broadcasts everything over WebSocket. The frontend uses Alpine.js for a reactive tabbed detail panel.

**Tech Stack:** Python/FastAPI, SQLite (VirtualFS), Alpine.js (CDN), vanilla JS, WebSocket

**Spec:** `docs/superpowers/specs/2026-03-10-agent-visibility-design.md`

---

## File Structure

### Files to Modify
- `src/agentdb/agents/tools.py` — Add event buffer to CityTools
- `src/agentdb/agents/swarm.py` — Thread event buffer through to CityTools
- `src/agentdb/dashboard/app.py` — Add `/api/file` endpoint + `fs_snapshot` on WS connect
- `src/agentdb/dashboard/static/app.js` — Handle new WS message types, dispatch custom events
- `src/agentdb/dashboard/static/index.html` — Alpine.js CDN, restructured detail panel
- `src/agentdb/dashboard/static/style.css` — Tab bar, conversation cards, diff, tree, flash animations
- `main.py` — Wire event buffer, post-cycle broadcast logic

### Files to Create
- `src/agentdb/dashboard/static/detail-tabs.js` — Alpine component for tabbed detail panel
- `tests/test_tools_events.py` — Tests for CityTools event buffer
- `tests/test_app_api.py` — Tests for `/api/file` endpoint and `fs_snapshot`

### Files NOT Changed
- `src/agentdb/dashboard/static/graph.js` — Calls `window.selectService()` which stays same signature
- `src/agentdb/db/filesystem.py` — No changes
- `src/agentdb/db/kvstore.py` — No changes
- `src/agentdb/db/overlay.py` — No changes
- `src/agentdb/simulation/` — No changes

---

## Chunk 1: Server-Side Event Buffer

### Task 1: CityTools Event Buffer

**Files:**
- Modify: `src/agentdb/agents/tools.py`
- Test: `tests/test_tools_events.py`

- [ ] **Step 1: Write failing tests for event buffer**

Create `tests/test_tools_events.py`:

```python
import json
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools_events.py -v`
Expected: FAIL — `CityTools.__init__` doesn't accept `event_buffer` parameter

- [ ] **Step 3: Implement event buffer in CityTools**

Modify `src/agentdb/agents/tools.py`:

1. Add `event_buffer` parameter to `__init__`:

```python
def __init__(self, fs: VirtualFS, kv: KVStore, overlay: OverlayFS,
             event_buffer: list | None = None):
    self.fs = fs
    self.kv = kv
    self.overlay = overlay
    self._incident_counter = 0
    self._events = event_buffer if event_buffer is not None else []
```

2. Add `_emit` helper:

```python
def _emit(self, event_type: str, **kwargs) -> None:
    self._events.append({"type": event_type, **kwargs})
```

3. Update `write_file`:

```python
def write_file(self, path: str, content: str) -> str:
    if err := self._validate_path(path):
        return err
    old = self.fs.read_file(path)
    self.fs.write_file(path, content)
    self._emit("code_diff", path=path, old_content=old,
               new_content=content, action="write")
    self._emit("fs_change", path=path, action="write", size=len(content))
    return f"Written {len(content)} bytes to {path}"
```

4. Update `deploy_staging`:

```python
def deploy_staging(self, path: str, content: str) -> str:
    if err := self._validate_path(path):
        return err
    old = self.overlay.read_file(path)
    self.overlay.write_file(path, content)
    self._emit("code_diff", path=path, old_content=old,
               new_content=content, action="stage")
    self._emit("fs_change", path=path, action="write", size=len(content))
    return f"Staged {len(content)} bytes to {path}"
```

5. Update `patch_file` (same pattern as `deploy_staging`):

```python
def patch_file(self, path: str, content: str) -> str:
    if err := self._validate_path(path):
        return err
    old = self.overlay.read_file(path)
    self.overlay.write_file(path, content)
    self._emit("code_diff", path=path, old_content=old,
               new_content=content, action="stage")
    self._emit("fs_change", path=path, action="write", size=len(content))
    return f"Patched {path} in staging ({len(content)} bytes)"
```

7. Update `hotfix_prod`:

```python
def hotfix_prod(self, service: str) -> str:
    changes = self.overlay.list_changes()
    if not changes:
        return f"No staged changes to merge (context: {service})"
    for change in changes:
        if change.change_type == "modified":
            old = self.fs.read_file(change.path)
            new = self.overlay.read_file(change.path)
            self._emit("code_diff", path=change.path, old_content=old,
                       new_content=new, action="merge")
            self._emit("fs_change", path=change.path, action="write",
                       size=len(new) if new else 0)
        elif change.change_type == "deleted":
            self._emit("fs_change", path=change.path, action="delete", size=0)
    self.overlay.merge()
    return f"Hotfix applied: {len(changes)} files merged to production (context: {service})"
```

8. Update `rollback`:

```python
def rollback(self, service: str) -> str:
    changes = self.overlay.list_changes()
    for change in changes:
        self._emit("fs_change", path=change.path, action="delete", size=0)
    self.overlay.discard()
    return f"Rolled back all staged changes (context: {service})"
```

9. Update `create_incident` — add after `self.fs.write_file(...)`:

```python
self._emit("fs_change", path=f"/city/incidents/{inc_id}.json",
           action="write", size=len(incident))
```

10. Update `assign_task` — add after `self.fs.write_file(...)`:

```python
self._emit("fs_change", path=f"/city/plans/{task_id}.json",
           action="write", size=len(task_data))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools_events.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass (existing tests should still work since `event_buffer` is optional)

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/agents/tools.py tests/test_tools_events.py
git commit -m "feat: add event buffer to CityTools for agent visibility"
```

---

### Task 2: Thread Event Buffer Through Swarm

**Files:**
- Modify: `src/agentdb/agents/swarm.py`

- [ ] **Step 1: Update `build_swarm` to accept and pass event_buffer**

Modify `src/agentdb/agents/swarm.py` — change the `build_swarm` function signature:

```python
def build_swarm(fs: VirtualFS, kv: KVStore, overlay: OverlayFS,
                event_buffer: list | None = None):
    """Build and compile the LangGraph Swarm with all city agents."""
    city_tools = CityTools(fs=fs, kv=kv, overlay=overlay,
                           event_buffer=event_buffer)
    # ... rest unchanged
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/agents/swarm.py
git commit -m "feat: thread event_buffer through build_swarm to CityTools"
```

---

### Task 3: `/api/file` Endpoint + `fs_snapshot` on WS Connect

**Files:**
- Modify: `src/agentdb/dashboard/app.py`
- Test: `tests/test_app_api.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_app_api.py`:

```python
import json
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.db.schema import init_db
from agentdb.dashboard.broadcast import Broadcaster
from agentdb.dashboard.app import create_app, build_fs_tree
import sqlite3


@pytest.fixture
def app_fixtures():
    conn = sqlite3.connect(":memory:")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_app_api.py -v`
Expected: FAIL — `create_app` doesn't accept `fs` parameter, `build_fs_tree` doesn't exist

- [ ] **Step 3: Implement `/api/file` endpoint and `build_fs_tree`**

Modify `src/agentdb/dashboard/app.py`:

1. Add `fs` parameter to `create_app`:

```python
def create_app(broadcaster: Broadcaster, engine=None, fs=None) -> FastAPI:
```

2. Add `build_fs_tree` as a module-level function:

```python
def build_fs_tree(fs) -> dict:
    """Build a nested dict tree from VirtualFS. Files=int(size), dirs=dict."""
    def _walk(path: str) -> dict:
        tree = {}
        for name in fs.list_dir(path):
            if name.startswith("__"):  # skip __overlay__ internal namespace
                continue
            child = f"{path}/{name}" if path != "/" else f"/{name}"
            content = fs.read_file(child)
            if content is not None:
                tree[name] = len(content.encode())
            else:
                subtree = _walk(child)
                if subtree:
                    tree[name] = subtree
        return tree
    return _walk("/")
```

3. Add imports at the top of `app.py` (alongside existing imports):

```python
from fastapi import Query
from fastapi.responses import PlainTextResponse, JSONResponse
```

4. Add the `/api/file` endpoint inside `create_app`:

```python

@app.get("/api/file")
async def get_file(path: str = Query(...)):
    if not path.startswith("/city/"):
        return JSONResponse({"error": "Path must start with /city/"}, status_code=400)
    if fs is None:
        return JSONResponse({"error": "Filesystem not available"}, status_code=500)
    content = fs.read_file(path)
    if content is None:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return PlainTextResponse(content)
```

5. Send `fs_snapshot` when WebSocket connects — add inside the `try` block, after `queue = broadcaster.subscribe()` and before `read_task = asyncio.create_task(read_client())`:

```python
if fs:
    tree = build_fs_tree(fs)
    snapshot = json.dumps({"type": "fs_snapshot", "data": {"tree": tree}})
    await ws.send_text(snapshot)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_app_api.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/dashboard/app.py tests/test_app_api.py
git commit -m "feat: add /api/file endpoint and fs_snapshot on WS connect"
```

---

### Task 4: Wire Event Buffer + Post-Cycle Broadcast in main.py

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Create event buffer and pass to build_swarm**

In `main.py`, after the `# 5. Broadcaster` section:

```python
event_buffer: list = []
```

Update `build_swarm` call:

```python
swarm = build_swarm(fs, kv, overlay, event_buffer=event_buffer)
```

Update `create_app` call:

```python
app = create_app(broadcaster, engine=engine, fs=fs)
```

- [ ] **Step 2: Add cycle counter and message extraction to run_agents()**

Add `cycle_counter` inside `main()`, alongside `event_buffer` (NOT at module level — `nonlocal` requires enclosing function scope):

```python
cycle_counter = 0
```

Replace the current `run_agents()` body with the post-cycle broadcast logic. After `swarm.ainvoke()` returns:

1. Increment `cycle_counter`
2. Walk `result["messages"]` to extract `agent_message` events:
   - For each message, check if it has a `name` attribute and non-empty `content`
   - Extract `tool_calls` from messages that have them (list of `{"name": ...}` dicts)
   - Detect handoffs by checking for tool call names matching `transfer_to_*`
   - Broadcast each as `agent_message`
3. Enrich and broadcast buffered events:
   - Add `tick` and `agent` fields to each event in `event_buffer`
   - For agent attribution, use the most recent agent name seen in the message walk
   - Broadcast each as its `type` (`code_diff` or `fs_change`)
4. Clear `event_buffer`

Here is the complete updated `run_agents`:

```python
async def run_agents() -> None:
    nonlocal cycle_counter
    if swarm is None:
        return

    for name in all_agent_names:
        await broadcaster.broadcast("agent_update", {
            "agent": name, "status": "working",
            "message": f"Checking city health (tick {engine.tick})...",
            "tick": engine.tick,
        })

    try:
        from langchain_core.messages import HumanMessage, AIMessage

        prompt = (
            f"Tick {engine.tick}. Check city health. "
            "If any service is degraded or failed, create an incident "
            "and hand off to the appropriate agent. Otherwise report status."
        )
        result = await swarm.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": thread_id}},
        )

        cycle_counter += 1

        # --- Extract agent_message events ---
        participated: dict[str, str] = {}
        current_agent = "monitor"
        for msg in result["messages"]:
            agent_name = getattr(msg, "name", None)
            if agent_name and agent_name in all_agent_names:
                current_agent = agent_name

            if not isinstance(msg, AIMessage):
                continue
            if not agent_name or agent_name not in all_agent_names:
                continue
            if not getattr(msg, "content", ""):
                continue

            tools_used = []
            handoff_to = None
            for tc in getattr(msg, "tool_calls", []) or []:
                tool_name = tc.get("name", "")
                if tool_name.startswith("transfer_to_"):
                    handoff_to = tool_name.replace("transfer_to_", "")
                else:
                    tools_used.append(tool_name)

            await broadcaster.broadcast("agent_message", {
                "cycle_id": cycle_counter,
                "tick": engine.tick,
                "agent": agent_name,
                "message": msg.content[:500],
                "tools_used": tools_used,
                "handoff_to": handoff_to,
            })
            participated[agent_name] = msg.content[:200]

        # --- Broadcast buffered file events ---
        # Note: current_agent is approximate — LangGraph's InMemorySaver
        # accumulates messages across ticks, so this reflects the last
        # agent that was active in the full conversation history.
        for event in event_buffer:
            event["tick"] = engine.tick
            event["agent"] = current_agent
            await broadcaster.broadcast(event.pop("type"), event)
        event_buffer.clear()

        # --- Agent status updates ---
        for name, summary in participated.items():
            await broadcaster.broadcast("agent_update", {
                "agent": name, "status": "acted",
                "message": summary, "tick": engine.tick,
            })
            await broadcaster.broadcast("city_event", {
                "event_type": "agent_action", "service": name,
                "severity": "low",
                "message": f"Agent {name}: {summary[:120]}",
                "tick": engine.tick,
            })
        for name in all_agent_names:
            if name not in participated:
                await broadcaster.broadcast("agent_update", {
                    "agent": name, "status": "idle",
                    "message": "", "tick": engine.tick,
                })

        print(f"[tick {engine.tick}] Agents: {', '.join(participated.keys()) or 'none'}")
    except Exception as exc:
        print(f"[tick {engine.tick}] Agent error: {exc}")
        traceback.print_exc()
        event_buffer.clear()
        for name in all_agent_names:
            await broadcaster.broadcast("agent_update", {
                "agent": name, "status": "error",
                "message": str(exc)[:200], "tick": engine.tick,
            })
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: wire event buffer and post-cycle broadcast in main"
```

---

## Chunk 2: Frontend — Alpine.js Tabbed Panel

### Task 5: Update app.js — New Message Handlers

**Files:**
- Modify: `src/agentdb/dashboard/static/app.js`

- [ ] **Step 1: Add new cases to handleMessage switch**

Add these cases after the existing `agent_update` case in the `handleMessage` function:

```javascript
case "agent_message":
  window.dispatchEvent(new CustomEvent("agentdb:agent-message", { detail: msg.data }));
  break;
case "code_diff":
  window.dispatchEvent(new CustomEvent("agentdb:code-diff", { detail: msg.data }));
  break;
case "fs_change":
  window.dispatchEvent(new CustomEvent("agentdb:fs-change", { detail: msg.data }));
  break;
case "fs_snapshot":
  window.dispatchEvent(new CustomEvent("agentdb:fs-snapshot", { detail: msg.data }));
  break;
```

- [ ] **Step 2: Remove `window.selectService` from app.js**

Delete the entire `window.selectService = function (...)` block (lines 232-277 in current file). This function moves to `detail-tabs.js`.

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/dashboard/static/app.js
git commit -m "feat: dispatch custom events for new WS message types"
```

---

### Task 6: Create detail-tabs.js — Alpine Component

**Files:**
- Create: `src/agentdb/dashboard/static/detail-tabs.js`

- [ ] **Step 1: Write the Alpine component**

Create `src/agentdb/dashboard/static/detail-tabs.js`:

```javascript
/* ============================================================
   AgentDB Dashboard -- Tabbed Detail Panel (Alpine.js)
   ============================================================ */

document.addEventListener("alpine:init", function () {

  var AGENT_COLORS = {
    mayor: "#81a2be",
    engineer: "#b294bb",
    monitor: "#b5bd68",
    fixer: "#f0c674"
  };

  var MAX_CONVERSATIONS = 50;
  var MAX_DIFFS = 20;

  Alpine.data("detailPanel", function () {
    return {
      tab: "conversations",
      conversations: [],
      diffs: [],
      fsTree: {},
      selectedFile: null,
      fileContent: null,
      serviceDetail: null,

      init: function () {
        var self = this;

        window.addEventListener("agentdb:agent-message", function (e) {
          self.conversations.unshift(e.detail);
          if (self.conversations.length > MAX_CONVERSATIONS) {
            self.conversations.pop();
          }
        });

        window.addEventListener("agentdb:code-diff", function (e) {
          self.diffs.unshift(e.detail);
          if (self.diffs.length > MAX_DIFFS) {
            self.diffs.pop();
          }
        });

        window.addEventListener("agentdb:fs-snapshot", function (e) {
          self.fsTree = e.detail.tree || {};
        });

        window.addEventListener("agentdb:fs-change", function (e) {
          self.applyFsChange(e.detail);
        });
      },

      // --- Tab switching ---
      switchTab: function (name) {
        this.tab = name;
      },

      // --- Agent colors ---
      agentColor: function (name) {
        return AGENT_COLORS[name] || "#8c8f93";
      },

      // --- Diff computation ---
      computeDiff: function (oldContent, newContent) {
        var oldLines = (oldContent || "").split("\n");
        var newLines = (newContent || "").split("\n");
        var result = [];
        var maxLen = Math.max(oldLines.length, newLines.length);

        for (var i = 0; i < maxLen; i++) {
          var oldLine = i < oldLines.length ? oldLines[i] : null;
          var newLine = i < newLines.length ? newLines[i] : null;

          if (oldLine === newLine) {
            result.push({ type: "same", text: " " + (oldLine || "") });
          } else {
            if (oldLine !== null) {
              result.push({ type: "removed", text: "-" + oldLine });
            }
            if (newLine !== null) {
              result.push({ type: "added", text: "+" + newLine });
            }
          }
        }
        return result;
      },

      // --- Filesystem tree ---
      applyFsChange: function (data) {
        var parts = data.path.replace(/^\//, "").split("/");
        if (data.action === "write") {
          var node = this.fsTree;
          for (var i = 0; i < parts.length - 1; i++) {
            if (!node[parts[i]] || typeof node[parts[i]] !== "object") {
              node[parts[i]] = {};
            }
            node = node[parts[i]];
          }
          node[parts[parts.length - 1]] = data.size || 0;
        } else if (data.action === "delete") {
          var node = this.fsTree;
          for (var i = 0; i < parts.length - 1; i++) {
            if (!node[parts[i]]) return;
            node = node[parts[i]];
          }
          delete node[parts[parts.length - 1]];
        }
        // Trigger flash animation via DOM
        this.$nextTick(function () {
          var el = document.querySelector('[data-fspath="' + data.path + '"]');
          if (el) {
            el.classList.remove("fs-flash-write", "fs-flash-delete");
            void el.offsetWidth; // force reflow
            el.classList.add(data.action === "write" ? "fs-flash-write" : "fs-flash-delete");
          }
        });
      },

      sortedEntries: function (obj) {
        if (!obj || typeof obj !== "object") return [];
        var entries = Object.entries(obj);
        // Directories first, then files, both alphabetical
        entries.sort(function (a, b) {
          var aIsDir = typeof a[1] === "object";
          var bIsDir = typeof b[1] === "object";
          if (aIsDir !== bIsDir) return aIsDir ? -1 : 1;
          return a[0].localeCompare(b[0]);
        });
        return entries;
      },

      isDir: function (value) {
        return typeof value === "object" && value !== null;
      },

      loadFile: function (path) {
        var self = this;
        self.selectedFile = path;
        self.fileContent = "Loading...";
        fetch("/api/file?path=" + encodeURIComponent(path))
          .then(function (r) {
            if (!r.ok) throw new Error("Not found");
            return r.text();
          })
          .then(function (text) { self.fileContent = text; })
          .catch(function () { self.fileContent = "Error loading file"; });
      },

      // --- Service Detail (replaces window.selectService) ---
      selectService: function (name, status, load, capacity) {
        this.serviceDetail = {
          name: name,
          status: status,
          load: load,
          capacity: capacity,
          health: capacity > 0 ? Math.min(100, ((capacity - load) / capacity * 100)).toFixed(0) : 0
        };
        this.tab = "service";
      }
    };
  });

  // Expose selectService globally for graph.js compatibility
  window.selectService = function (name, status, load, capacity) {
    var el = document.querySelector("[x-data]");
    if (el && el.__x) {
      el.__x.$data.selectService(name, status, load, capacity);
    } else {
      // Alpine v3: use $data from the component
      var component = Alpine.$data(document.querySelector(".panel-detail"));
      if (component) {
        component.selectService(name, status, load, capacity);
      }
    }
  };

  // Cross-linking: clicking agent card switches to conversations
  document.querySelectorAll(".agent-card").forEach(function (card) {
    card.addEventListener("click", function () {
      var component = Alpine.$data(document.querySelector(".panel-detail"));
      if (component) {
        component.tab = "conversations";
      }
    });
  });
});
```

- [ ] **Step 2: Commit**

```bash
git add src/agentdb/dashboard/static/detail-tabs.js
git commit -m "feat: add Alpine.js detail panel component"
```

---

### Task 7: Update index.html — Alpine Markup

**Files:**
- Modify: `src/agentdb/dashboard/static/index.html`

- [ ] **Step 1: Add Alpine.js CDN and detail-tabs.js script tags**

Before the closing `</body>` tag, add the Alpine CDN before the existing scripts. The order should be:

```html
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js"></script>
<script src="/static/graph.js"></script>
<script src="/static/app.js"></script>
<script src="/static/detail-tabs.js"></script>
```

- [ ] **Step 2: Replace the detail panel section**

Replace the entire `<section class="panel panel-detail">` block with:

```html
<!-- Bottom: Tabbed Detail Panel -->
<section class="panel panel-detail" x-data="detailPanel">
  <div class="panel-header tab-bar">
    <button class="tab-btn" :class="{ active: tab === 'conversations' }" @click="tab = 'conversations'">Conversations</button>
    <button class="tab-btn" :class="{ active: tab === 'diffs' }" @click="tab = 'diffs'">Code Diffs</button>
    <button class="tab-btn" :class="{ active: tab === 'filesystem' }" @click="tab = 'filesystem'">Filesystem</button>
    <button class="tab-btn" :class="{ active: tab === 'service' }" @click="tab = 'service'">Service Detail</button>
  </div>

  <!-- Conversations Tab -->
  <div class="tab-content" x-show="tab === 'conversations'" x-cloak>
    <template x-if="conversations.length === 0">
      <div class="detail-placeholder">Waiting for agent activity...</div>
    </template>
    <template x-for="msg in conversations" :key="msg.cycle_id + '-' + msg.agent">
      <div class="conversation-card" :style="'border-left-color:' + agentColor(msg.agent)">
        <div class="conv-header">
          <span class="conv-agent" :style="'color:' + agentColor(msg.agent)" x-text="msg.agent"></span>
          <span class="conv-tick" x-text="'#' + msg.tick"></span>
        </div>
        <div class="conv-body" x-text="msg.message"></div>
        <div class="conv-footer">
          <template x-for="tool in msg.tools_used || []">
            <span class="conv-tool-tag" x-text="tool"></span>
          </template>
          <template x-if="msg.handoff_to">
            <span class="conv-handoff">&rarr; <span x-text="msg.handoff_to"></span></span>
          </template>
        </div>
      </div>
    </template>
  </div>

  <!-- Code Diffs Tab -->
  <div class="tab-content" x-show="tab === 'diffs'" x-cloak>
    <template x-if="diffs.length === 0">
      <div class="detail-placeholder">No code changes yet...</div>
    </template>
    <template x-for="(diff, idx) in diffs" :key="idx">
      <details class="diff-block" open>
        <summary class="diff-header">
          <span class="diff-path" x-text="diff.path"></span>
          <span class="diff-meta">
            <span class="conv-tool-tag" x-text="diff.action"></span>
            <span class="conv-agent" :style="'color:' + agentColor(diff.agent)" x-text="diff.agent"></span>
            <span class="conv-tick" x-text="'#' + diff.tick"></span>
          </span>
        </summary>
        <div class="diff-content">
          <template x-for="line in computeDiff(diff.old_content, diff.new_content)">
            <div class="diff-line" :class="line.type" x-text="line.text"></div>
          </template>
        </div>
      </details>
    </template>
  </div>

  <!-- Filesystem Tab -->
  <div class="tab-content tab-filesystem" x-show="tab === 'filesystem'" x-cloak>
    <div class="fs-tree">
      <template x-if="Object.keys(fsTree).length === 0">
        <div class="detail-placeholder">Waiting for filesystem snapshot...</div>
      </template>
      <template x-for="[name, value] in sortedEntries(fsTree)" :key="name">
        <div x-data="{ open: true }">
          <template x-if="isDir(value)">
            <div>
              <div class="fs-dir" @click="open = !open">
                <span class="fs-toggle" x-text="open ? '&#9660;' : '&#9654;'"></span>
                <span x-text="name"></span>/
              </div>
              <div x-show="open" style="padding-left: 16px;">
                <template x-for="[cname, cval] in sortedEntries(value)" :key="cname">
                  <div>
                    <template x-if="isDir(cval)">
                      <div x-data="{ subOpen: false }">
                        <div class="fs-dir" @click="subOpen = !subOpen">
                          <span class="fs-toggle" x-text="subOpen ? '&#9660;' : '&#9654;'"></span>
                          <span x-text="cname"></span>/
                        </div>
                        <div x-show="subOpen" style="padding-left: 16px;">
                          <template x-for="[fname, fval] in sortedEntries(cval)" :key="fname">
                            <div class="fs-file" :data-fspath="'/' + name + '/' + cname + '/' + fname"
                                 @click="loadFile('/' + name + '/' + cname + '/' + fname)">
                              <span x-text="fname"></span>
                              <span class="fs-size" x-text="typeof fval === 'number' ? fval + 'B' : ''"></span>
                            </div>
                          </template>
                        </div>
                      </div>
                    </template>
                    <template x-if="!isDir(cval)">
                      <div class="fs-file" :data-fspath="'/' + name + '/' + cname"
                           @click="loadFile('/' + name + '/' + cname)">
                        <span x-text="cname"></span>
                        <span class="fs-size" x-text="cval + 'B'"></span>
                      </div>
                    </template>
                  </div>
                </template>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>
    <div class="fs-preview" x-show="selectedFile">
      <div class="fs-preview-header" x-text="selectedFile || ''"></div>
      <pre class="fs-preview-content" x-text="fileContent || ''"></pre>
    </div>
  </div>

  <!-- Service Detail Tab -->
  <div class="tab-content" x-show="tab === 'service'" x-cloak>
    <template x-if="!serviceDetail">
      <div class="detail-placeholder">Click a service node on the map to view details</div>
    </template>
    <template x-if="serviceDetail">
      <div>
        <div class="panel-badge" x-text="serviceDetail.name" style="margin-bottom: 8px;"></div>
        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-label">Status</span>
            <span class="detail-value" :class="serviceDetail.status" x-text="serviceDetail.status.toUpperCase()"></span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Load</span>
            <span class="detail-value" x-text="(serviceDetail.load * 100).toFixed(1) + '%'"></span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Capacity</span>
            <span class="detail-value" x-text="(serviceDetail.capacity * 100).toFixed(1) + '%'"></span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Headroom</span>
            <span class="detail-value" :class="serviceDetail.status" x-text="serviceDetail.health + '%'"></span>
          </div>
        </div>
      </div>
    </template>
  </div>
</section>
```

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/dashboard/static/index.html
git commit -m "feat: restructure detail panel with Alpine.js tabs"
```

---

### Task 8: Update style.css — Tab Bar, Conversations, Diffs, Tree, Flash Animations

**Files:**
- Modify: `src/agentdb/dashboard/static/style.css`

- [ ] **Step 1: Replace the Service Detail Panel section and add new styles**

Replace the existing `/* Service Detail Panel */` section (`.panel-detail { max-height: 140px; }` and related rules) with expanded styles. Then add new sections for tabs, conversations, diffs, tree view, and flash animations.

Remove `max-height: 140px` from `.panel-detail`. Set the grid to give the detail panel more space:

```css
.dashboard-grid {
  grid-template-rows: 1fr auto;  /* changed from 1fr 1fr auto */
}
```

Wait — this changes the layout significantly. The actual CSS change needed:

Update `.dashboard-grid` to:
```css
grid-template-rows: 3fr 3fr 5fr;
```

This gives the top two rows 3 parts each and the detail panel 5 parts (~45%).

Remove `max-height: 140px` from `.panel-detail`.

Add the following CSS sections after the existing agent status styles:

```css
/* ============================================================
   Tab Bar
   ============================================================ */

.tab-bar {
  display: flex;
  gap: 0;
  padding: 0 8px;
}

.tab-btn {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 8px 14px;
  cursor: pointer;
  transition: all 0.15s ease;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.tab-btn:hover {
  color: var(--text-secondary);
}

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px 10px;
}

[x-cloak] { display: none !important; }

/* ============================================================
   Conversations Tab
   ============================================================ */

.conversation-card {
  background: var(--bg-secondary);
  border-left: 3px solid var(--text-muted);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  margin-bottom: 6px;
}

.conv-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.conv-agent {
  font-size: 11px;
  font-weight: 600;
  text-transform: capitalize;
}

.conv-tick {
  font-size: 9px;
  color: var(--text-muted);
}

.conv-body {
  font-size: 11px;
  color: var(--text-primary);
  line-height: 1.5;
  margin-bottom: 4px;
  max-height: 60px;
  overflow: hidden;
  cursor: pointer;
}

.conv-body:hover {
  max-height: none;
}

.conv-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.conv-tool-tag {
  font-size: 9px;
  color: var(--text-muted);
  background: var(--bg-primary);
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid var(--border-subtle);
}

.conv-handoff {
  font-size: 9px;
  color: var(--accent);
  margin-left: 4px;
}

/* ============================================================
   Code Diffs Tab
   ============================================================ */

.diff-block {
  margin-bottom: 8px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.diff-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: var(--bg-secondary);
  cursor: pointer;
  font-size: 10px;
}

.diff-path {
  color: var(--accent);
  font-weight: 500;
}

.diff-meta {
  display: flex;
  gap: 6px;
  align-items: center;
}

.diff-content {
  padding: 6px 0;
  background: var(--bg-primary);
  overflow-x: auto;
}

.diff-line {
  font-size: 11px;
  font-family: var(--font-mono);
  padding: 0 10px;
  white-space: pre;
  line-height: 1.6;
}

.diff-line.same {
  color: var(--text-secondary);
}

.diff-line.added {
  color: var(--status-ok);
  background: rgba(181, 189, 104, 0.08);
}

.diff-line.removed {
  color: var(--status-failed);
  background: rgba(204, 102, 102, 0.08);
}

/* ============================================================
   Filesystem Tab
   ============================================================ */

.tab-filesystem {
  display: flex;
  gap: 8px;
}

.fs-tree {
  flex: 1;
  overflow-y: auto;
  min-width: 0;
}

.fs-dir {
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--radius-sm);
}

.fs-dir:hover {
  background: var(--bg-elevated);
}

.fs-toggle {
  font-size: 8px;
  display: inline-block;
  width: 12px;
  color: var(--text-muted);
}

.fs-file {
  font-size: 11px;
  color: var(--text-primary);
  padding: 2px 4px 2px 16px;
  cursor: pointer;
  border-radius: var(--radius-sm);
  display: flex;
  justify-content: space-between;
  transition: background 0.5s ease;
}

.fs-file:hover {
  background: var(--bg-elevated);
}

.fs-size {
  font-size: 9px;
  color: var(--text-muted);
}

.fs-preview {
  flex: 1;
  background: var(--bg-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.fs-preview-header {
  font-size: 10px;
  color: var(--accent);
  padding: 6px 10px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-subtle);
}

.fs-preview-content {
  font-size: 11px;
  color: var(--text-primary);
  padding: 8px 10px;
  margin: 0;
  overflow: auto;
  flex: 1;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ============================================================
   Flash Animations
   ============================================================ */

@keyframes fs-flash-write {
  0%   { background: rgba(240, 198, 116, 0.3); }
  100% { background: transparent; }
}

@keyframes fs-flash-delete {
  0%   { background: rgba(204, 102, 102, 0.3); }
  100% { background: transparent; }
}

.fs-flash-write {
  animation: fs-flash-write 1.5s ease-out;
}

.fs-flash-delete {
  animation: fs-flash-delete 1.5s ease-out;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/agentdb/dashboard/static/style.css
git commit -m "feat: add styles for tabs, conversations, diffs, filesystem, flash animations"
```

---

### Task 9: Integration Test — Manual Verification

**Files:** None (manual testing)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -x -q`
Expected: All tests pass

- [ ] **Step 2: Start the server**

```bash
rm -f city.db && uv run python main.py
```

- [ ] **Step 3: Verify in browser**

Open `http://localhost:8000` and verify:

1. **Tick counter** increments every 5 seconds
2. **Conversations tab** populates when an agent cycle completes (20-30s)
3. **Code Diffs tab** shows diffs when agents write/patch files
4. **Filesystem tab** shows the directory tree on connect, files flash on change
5. **Service Detail tab** populates when clicking a service node on the map
6. **Tab switching** works, cross-linking from agent cards switches to conversations

- [ ] **Step 4: Commit all remaining changes (if any tweaks needed)**

```bash
git add -A
git commit -m "feat: agent visibility — tabbed detail panel with conversations, diffs, filesystem"
```
