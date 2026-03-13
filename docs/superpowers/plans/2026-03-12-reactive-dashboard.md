# Reactive Dashboard Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent behavior visible and compelling through reactive graph animations (pulse, shake, glow, cascade edge pulses, agent presence dots) and a unified event chip bar.

**Architecture:** Two small backend changes (add `source` field to CityEvent for cascades, add `service` field to agent_message broadcasts). All visual work is frontend-only: extend `graph.js` render loop with per-node/per-edge transition state, add unified `recentActivity[]` in `app.js` that merges 4 message types into clickable chips below the Canvas.

**Tech Stack:** Vanilla JS, Canvas 2D, Alpine.js, FastAPI (minor), Python dataclasses

**Spec:** `docs/superpowers/specs/2026-03-12-reactive-dashboard-design.md`

---

## Chunk 1: Backend Changes + Reactive Graph

### Task 1: Add `source` field to CityEvent

The simulation engine emits cascade failure events but only includes the source service in free-text. We need a structured `source` field so the frontend can animate the exact edge.

**Files:**
- Modify: `src/agentdb/simulation/events.py:36-51`
- Modify: `src/agentdb/simulation/engine.py:99-113`
- Test: `tests/test_engine.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_engine.py`:

```python
async def test_cascade_event_has_source_field(db):
    """Cascade events must include a structured 'source' field."""
    fs, kv = _setup_city(db)
    # Break power-grid so it fails and cascades
    fs.write_file(
        "/city/services/power-grid/main.py",
        "def handle_load(l, c): return 1/0",
    )
    events_received = []
    engine = SimulationEngine(db, fs, kv, seed=42)
    engine.on_event(lambda e: events_received.append(e))
    await engine.step()
    cascade_events = [
        e for e in events_received if e.event_type.value == "cascade_failure"
    ]
    # power-grid has dependents, so at least one cascade should fire
    assert len(cascade_events) >= 1, "Expected at least one cascade event"
    for e in cascade_events:
        assert hasattr(e, "source"), "CityEvent missing 'source' field"
        assert e.source == "power-grid"
        d = e.to_dict()
        assert "source" in d
        assert d["source"] == "power-grid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_engine.py::test_cascade_event_has_source_field -v`
Expected: FAIL with `AssertionError: CityEvent missing 'source' field`

- [ ] **Step 3: Add `source` field to CityEvent dataclass**

In `src/agentdb/simulation/events.py`, change the `CityEvent` dataclass:

```python
@dataclass
class CityEvent:
    event_type: EventType
    service: str
    severity: Severity
    message: str
    tick: int
    source: str | None = None

    def to_dict(self) -> dict:
        d = {
            "event_type": self.event_type.value,
            "service": self.service,
            "severity": self.severity.value,
            "message": self.message,
            "tick": self.tick,
        }
        if self.source is not None:
            d["source"] = self.source
        return d
```

- [ ] **Step 4: Populate `source` in cascade loop**

In `src/agentdb/simulation/engine.py`, in the cascade failure section (~line 106), add `source=failed`:

```python
                    event = CityEvent(
                        event_type=EventType.CASCADE_FAILURE,
                        service=affected,
                        severity=Severity.CRITICAL,
                        message=f"{affected} affected by {failed} failure",
                        tick=self.tick,
                        source=failed,
                    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_engine.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/simulation/events.py src/agentdb/simulation/engine.py tests/test_engine.py
git commit -m "feat: add source field to CityEvent for cascade tracking"
```

---

### Task 2: Add `service` field to agent_message broadcasts

The `agent_message` WebSocket payload lacks a `service` field. Extract it from tool call arguments so the frontend can show agent presence on graph nodes.

**Files:**
- Modify: `src/agentdb/agents/runner.py:72-101`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_runner.py`:

```python
async def test_extract_service_from_tool_calls():
    """AgentRunner._extract_service should find service names in tool args."""
    from agentdb.agents.runner import AgentRunner
    # Test path-based extraction
    assert AgentRunner._extract_service([
        {"name": "read_file", "args": {"path": "/city/services/power-grid/main.py"}}
    ]) == "power-grid"
    # Test direct service argument
    assert AgentRunner._extract_service([
        {"name": "create_incident", "args": {"service": "water-system", "description": "down"}}
    ]) == "water-system"
    # Test no service extractable
    assert AgentRunner._extract_service([
        {"name": "read_city_state", "args": {}}
    ]) is None
    # Test empty tool calls
    assert AgentRunner._extract_service([]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_runner.py::test_extract_service_from_tool_calls -v`
Expected: FAIL with `AttributeError: type object 'AgentRunner' has no attribute '_extract_service'`

- [ ] **Step 3: Add `_extract_service` static method to AgentRunner**

In `src/agentdb/agents/runner.py`, add after the `__init__` method:

```python
    @staticmethod
    def _extract_service(tool_calls: list[dict]) -> str | None:
        """Extract the target service name from tool call arguments."""
        for tc in tool_calls:
            args = tc.get("args", {})
            # Check direct 'service' argument
            if "service" in args:
                return args["service"]
            # Check path argument for /city/services/<name>/...
            path = args.get("path", "")
            if path.startswith("/city/services/"):
                parts = path.split("/")
                if len(parts) >= 4:
                    return parts[3]
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_runner.py::test_extract_service_from_tool_calls -v`
Expected: PASS

- [ ] **Step 5: Wire `_extract_service` into `_process_messages`**

In `src/agentdb/agents/runner.py`, in the `_process_messages` method, add service extraction and include it in the broadcast. Change the tool_calls loop and broadcast section (~lines 84-100):

```python
            tools_used = []
            raw_tool_calls = []
            handoff_to = None
            for tc in getattr(msg, "tool_calls", []) or []:
                tool_name = tc.get("name", "")
                if tool_name.startswith("transfer_to_"):
                    handoff_to = tool_name.replace("transfer_to_", "")
                else:
                    tools_used.append(tool_name)
                    raw_tool_calls.append(tc)

            service = self._extract_service(raw_tool_calls)

            await self._broadcaster.broadcast("agent_message", {
                "cycle_id": self._cycle_counter,
                "tick": self._engine.tick,
                "agent": agent_name,
                "message": msg.content[:500],
                "tools_used": tools_used,
                "handoff_to": handoff_to,
                "service": service,
            })
```

- [ ] **Step 6: Run all runner tests**

Run: `uv run pytest tests/test_runner.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/agentdb/agents/runner.py tests/test_runner.py
git commit -m "feat: extract service name from tool calls in agent_message broadcasts"
```

---

### Task 3: Node transition state tracking in graph.js

Add per-node state to track status transitions, enabling animations. This task adds the data structures and detection logic only -- actual drawing comes in Task 4.

**Files:**
- Modify: `src/agentdb/dashboard/static/graph.js:26-33,232-238`

- [ ] **Step 1: Add transition state fields to node objects**

In `graph.js`, in the `fetch("/api/topology")` callback (~line 270), extend the node object:

```javascript
        services = data.services.map(function (id) {
          return {
            id: id,
            label: id.split("-").map(function (w) {
              return w.charAt(0).toUpperCase() + w.slice(1);
            }).join(" "),
            status: "ok",
            prevStatus: "ok",
            load: 0.5,
            capacity: data.capacities[id] || 1.0,
            x: 0,
            y: 0,
            // Transition animation state
            shakeStart: 0,
            glowStart: 0,
            glowColor: null,
            pulseStart: 0,
            recoveryStart: 0,
            agentDots: []   // [{agent, color, startTime}]
          };
        });
```

- [ ] **Step 2: Detect status transitions in `updateServiceNode`**

Replace `window.updateServiceNode` (~line 232):

```javascript
  window.updateServiceNode = function (id, status, load, capacity) {
    var node = findNode(id);
    if (!node) return;

    var oldStatus = node.status;
    node.status   = status   || node.status;
    node.load     = load     != null ? load     : node.load;
    node.capacity = capacity != null ? capacity : node.capacity;

    // Detect transitions
    var now = performance.now();
    if (oldStatus !== node.status) {
      node.prevStatus = oldStatus;
      if (node.status === "failed") {
        node.shakeStart = now;
        node.glowStart = now;
        node.glowColor = COLORS.failed;
      } else if (node.status === "degraded" && oldStatus === "ok") {
        node.pulseStart = now;
      } else if (node.status === "ok" && oldStatus !== "ok") {
        node.recoveryStart = now;
      }
    }
  };
```

- [ ] **Step 3: Verify manually**

Open `http://localhost:8000` in a browser, confirm the graph still renders correctly. Node objects now carry transition fields but no visual changes yet.

- [ ] **Step 4: Commit**

```bash
git add src/agentdb/dashboard/static/graph.js
git commit -m "feat: add node transition state tracking to graph.js"
```

---

### Task 4: Node status animations (pulse, shake, glow, recovery)

Draw visual effects based on the transition state fields added in Task 3.

**Files:**
- Modify: `src/agentdb/dashboard/static/graph.js:139-200`

- [ ] **Step 1: Add animation helper functions**

In `graph.js`, add before the `drawNode` function (~line 139):

```javascript
  // ---- Animation helpers ----

  function dampedSine(t, freq, decay) {
    return Math.sin(t * freq) * Math.exp(-t * decay);
  }
```

- [ ] **Step 2: Rewrite `drawNode` with animation effects**

Replace the entire `drawNode` function with:

```javascript
  function drawNode(node) {
    var isSelected = selectedService === node.id;
    var now = performance.now();
    var offsetX = 0;

    // Shake animation (failed transition, 0.5s)
    if (node.shakeStart > 0) {
      var elapsed = (now - node.shakeStart) / 1000;
      if (elapsed < 0.5) {
        offsetX = dampedSine(elapsed, 40, 6) * 3;
      } else {
        node.shakeStart = 0;
      }
    }

    var drawX = node.x + offsetX;
    var drawY = node.y;

    // Glow animation (failed transition, 3s fade)
    if (node.glowStart > 0) {
      var glowElapsed = (now - node.glowStart) / 1000;
      if (glowElapsed < 3) {
        var glowAlpha = 0.4 * (1 - glowElapsed / 3);
        ctx.save();
        var gradient = ctx.createRadialGradient(
          drawX, drawY, NODE_RADIUS,
          drawX, drawY, NODE_RADIUS + 20
        );
        gradient.addColorStop(0, node.glowColor || COLORS.failed);
        gradient.addColorStop(1, "transparent");
        ctx.globalAlpha = glowAlpha;
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(drawX, drawY, NODE_RADIUS + 20, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      } else {
        node.glowStart = 0;
      }
    }

    // Pulse scale (degraded, continuous 2s cycle)
    var pulseScale = 1.0;
    if (node.status === "degraded" && node.pulseStart > 0) {
      var pulseT = ((now - node.pulseStart) / 1000) % 2;
      pulseScale = 1 + 0.08 * Math.sin(pulseT * Math.PI);
    }

    // Recovery flash (ok after failure/degraded, 0.3s)
    if (node.recoveryStart > 0) {
      var recElapsed = (now - node.recoveryStart) / 1000;
      if (recElapsed < 0.3) {
        ctx.save();
        ctx.globalAlpha = 0.5 * (1 - recElapsed / 0.3);
        ctx.fillStyle = COLORS.ok;
        ctx.beginPath();
        ctx.arc(drawX, drawY, NODE_RADIUS + 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      } else {
        node.recoveryStart = 0;
      }
    }

    var statusColor = COLORS[node.status] || COLORS.ok;
    var scaledRadius = NODE_RADIUS * pulseScale;

    // Glow for selected
    if (isSelected) {
      ctx.save();
      ctx.shadowColor = COLORS.selected;
      ctx.shadowBlur = 16;
      ctx.beginPath();
      ctx.arc(drawX, drawY, scaledRadius + 2, 0, Math.PI * 2);
      ctx.strokeStyle = COLORS.selected;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.restore();
    }

    // Status ring
    ctx.beginPath();
    ctx.arc(drawX, drawY, scaledRadius, 0, Math.PI * 2);
    ctx.strokeStyle = statusColor;
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.stroke();

    // Node background
    ctx.beginPath();
    ctx.arc(drawX, drawY, scaledRadius - 2, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.nodeBg;
    ctx.fill();

    // Load arc
    if (node.load > 0) {
      var loadAngle = -Math.PI / 2 + Math.PI * 2 * Math.min(node.load, 1);
      ctx.beginPath();
      ctx.arc(drawX, drawY, scaledRadius - 6, -Math.PI / 2, loadAngle);
      ctx.strokeStyle = statusColor;
      ctx.lineWidth = 3;
      ctx.globalAlpha = 0.3;
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }

    // Status dot
    ctx.beginPath();
    ctx.arc(drawX, drawY, 5, 0, Math.PI * 2);
    ctx.fillStyle = statusColor;
    ctx.fill();

    // Label
    ctx.font = "500 11px 'JetBrains Mono', monospace";
    ctx.fillStyle = isSelected ? COLORS.selected : COLORS.text;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(node.label, drawX, drawY + LABEL_OFFSET);

    // Status text
    ctx.font = "400 9px 'JetBrains Mono', monospace";
    ctx.fillStyle = statusColor;
    ctx.fillText(node.status.toUpperCase(), drawX, drawY + LABEL_OFFSET + 15);

    // Agent presence dots
    if (node.agentDots.length > 0) {
      for (var ai = 0; ai < node.agentDots.length; ai++) {
        var dot = node.agentDots[ai];
        var dotAngle = -Math.PI / 2 + (ai * Math.PI * 2) / Math.max(node.agentDots.length, 4);
        var dotX = drawX + (NODE_RADIUS + 12) * Math.cos(dotAngle);
        var dotY = drawY + (NODE_RADIUS + 12) * Math.sin(dotAngle);

        ctx.beginPath();
        ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
        ctx.fillStyle = dot.color;
        ctx.fill();
        ctx.strokeStyle = COLORS.bg;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
  }
```

- [ ] **Step 3: Verify manually**

Start the server (`uv run python main.py`). Watch for:
- Degraded nodes pulsing yellow
- Failed nodes shaking then glowing red
- Recovery flash when a node returns to ok

- [ ] **Step 4: Commit**

```bash
git add src/agentdb/dashboard/static/graph.js
git commit -m "feat: add node status animations (pulse, shake, glow, recovery)"
```

---

### Task 5: Cascade edge pulse animation

When a `city_event` with `event_type: "cascade_failure"` arrives, animate the edge from `source` to `service`.

**Files:**
- Modify: `src/agentdb/dashboard/static/graph.js:86-123,284-290`
- Modify: `src/agentdb/dashboard/static/app.js:91-92`

- [ ] **Step 1: Add edge transition state**

In `graph.js`, where edges are built from topology (~line 285-290), extend each edge:

```javascript
        edges = [];
        Object.keys(data.edges).forEach(function (child) {
          data.edges[child].forEach(function (parent) {
            edges.push({
              from: parent,
              to: child,
              cascadeStart: 0,
              cascadeColor: null
            });
          });
        });
```

- [ ] **Step 2: Add public method to trigger cascade on an edge**

After `window.updateServiceNode`, add:

```javascript
  window.triggerCascadeEdge = function (sourceId, targetId) {
    for (var i = 0; i < edges.length; i++) {
      if (edges[i].from === sourceId && edges[i].to === targetId) {
        edges[i].cascadeStart = performance.now();
        edges[i].cascadeColor = COLORS.failed;
        return;
      }
    }
  };
```

- [ ] **Step 3: Draw cascade pulse in `drawEdges`**

In the `drawEdges` function, **inside the existing `for (var i = 0; i < edges.length; i++)` loop**, after the flow dot `ctx.fill()` call (~line 115) and before the direction arrow code (~line 117), add the cascade effect:

```javascript
      // Cascade pulse animation (0.4s travel + 2s red highlight)
      if (edges[i].cascadeStart > 0) {
        var cascadeElapsed = (performance.now() - edges[i].cascadeStart) / 1000;

        if (cascadeElapsed < 2.4) {
          // Highlight edge red
          var edgeAlpha = cascadeElapsed < 0.4 ? 1.0 : Math.max(0, 1 - (cascadeElapsed - 0.4) / 2);
          ctx.beginPath();
          ctx.moveTo(fromNode.x, fromNode.y);
          ctx.lineTo(toNode.x, toNode.y);
          ctx.strokeStyle = COLORS.failed;
          ctx.lineWidth = 3;
          ctx.globalAlpha = edgeAlpha;
          ctx.stroke();
          ctx.globalAlpha = 1.0;

          // Pulse dot traveling along edge (first 0.4s)
          if (cascadeElapsed < 0.4) {
            var pt = cascadeElapsed / 0.4;
            var px = fromNode.x + (toNode.x - fromNode.x) * pt;
            var py = fromNode.y + (toNode.y - fromNode.y) * pt;
            ctx.beginPath();
            ctx.arc(px, py, 5, 0, Math.PI * 2);
            ctx.fillStyle = COLORS.failed;
            ctx.fill();
          }
        } else {
          edges[i].cascadeStart = 0;
        }
      }
```

- [ ] **Step 4: Dispatch cascade event from app.js**

In `app.js`, in the `handleMessage` switch, update the `city_event` case (~line 91):

```javascript
      case "city_event":
        handleCityEvent(msg.data);
        // Trigger cascade edge animation
        if (msg.data.event_type === "cascade_failure" && msg.data.source) {
          if (typeof window.triggerCascadeEdge === "function") {
            window.triggerCascadeEdge(msg.data.source, msg.data.service);
          }
        }
        break;
```

- [ ] **Step 5: Verify manually**

Run the server. Wait for a cascade event (or break a service). Watch for:
- Red pulse traveling along the dependency edge
- Edge highlighting red then fading over 2s

- [ ] **Step 6: Commit**

```bash
git add src/agentdb/dashboard/static/graph.js src/agentdb/dashboard/static/app.js
git commit -m "feat: add cascade edge pulse animation"
```

---

### Task 6: Agent presence dots on graph nodes

Show which agent is working on which service node, based on `agent_message` events with a `service` field.

> **Spec deviation:** The spec mentions agent dots "slide from one node to another (lerp over 0.3s)." This plan implements instant teleportation for simplicity. Lerp animation is deferred to a follow-up if the instant version feels jarring. The existing codebase uses `window.` global functions for graph.js communication (e.g., `window.updateServiceNode`), so we follow that pattern rather than the spec's custom DOM events approach.

**Files:**
- Modify: `src/agentdb/dashboard/static/graph.js`
- Modify: `src/agentdb/dashboard/static/app.js:97-99,167`

- [ ] **Step 1: Add public method to update agent presence**

In `graph.js`, after `window.triggerCascadeEdge`, add:

```javascript
  var AGENT_COLORS = {
    mayor: "#81a2be",
    engineer: "#b294bb",
    monitor: "#b5bd68",
    fixer: "#f0c674"
  };

  window.updateAgentPresence = function (agentName, serviceId) {
    // Remove this agent from any previous node
    for (var i = 0; i < services.length; i++) {
      services[i].agentDots = services[i].agentDots.filter(function (d) {
        return d.agent !== agentName;
      });
    }
    // Add to new node (null means agent is idle)
    if (serviceId) {
      var node = findNode(serviceId);
      if (node) {
        node.agentDots.push({
          agent: agentName,
          color: AGENT_COLORS[agentName] || "#8c8f93",
          startTime: performance.now()
        });
      }
    }
  };
```

Note: Agent presence dots are already drawn in the `drawNode` function from Task 4.

- [ ] **Step 2: Wire agent_message to presence in app.js**

In `app.js`, update the `agent_message` case (~line 97):

```javascript
      case "agent_message":
        window.dispatchEvent(new CustomEvent("agentdb:agent-message", { detail: msg.data }));
        // Update agent presence on graph
        if (msg.data.service && typeof window.updateAgentPresence === "function") {
          window.updateAgentPresence(msg.data.agent, msg.data.service);
        }
        break;
```

- [ ] **Step 3: Clear agent presence on idle status**

In `app.js`, in `handleAgentUpdate`, after the `acted` timer branch (~line 183), add an idle check:

```javascript
    if (status === "idle" && typeof window.updateAgentPresence === "function") {
      window.updateAgentPresence(agent, null);
    }
```

- [ ] **Step 4: Verify manually**

Run the server with Ollama running. Watch for colored dots appearing around nodes when agents act, disappearing when idle.

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/dashboard/static/graph.js src/agentdb/dashboard/static/app.js
git commit -m "feat: add agent presence dots on graph nodes"
```

---

### Task 7: Dispatch `agentdb:service-selected` custom event

When a user clicks a graph node, dispatch a DOM event that other components (chip bar, detail panel) can listen to. This is the phase 2 contract.

**Files:**
- Modify: `src/agentdb/dashboard/static/graph.js:204-228`

- [ ] **Step 1: Dispatch custom event on node click**

In `graph.js`, in the `handleClick` function, update the click handling:

```javascript
    if (clicked) {
      selectedService = clicked.id;
      if (typeof window.selectService === "function") {
        window.selectService(clicked.label, clicked.status, clicked.load, clicked.capacity);
      }
      window.dispatchEvent(new CustomEvent("agentdb:service-selected", {
        detail: { service: clicked.id, label: clicked.label }
      }));
    } else {
      selectedService = null;
      window.dispatchEvent(new CustomEvent("agentdb:service-selected", {
        detail: { service: null, label: null }
      }));
    }
```

- [ ] **Step 2: Verify manually**

Open browser console, run:
```javascript
window.addEventListener("agentdb:service-selected", e => console.log("selected:", e.detail));
```
Click a node. Confirm the event fires with the service id.

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/dashboard/static/graph.js
git commit -m "feat: dispatch agentdb:service-selected custom event on node click"
```

---

## Chunk 2: Event Chip Bar

### Task 8: Unified activity model in app.js

Create the `recentActivity[]` array with the unified shape. All 4 message types push into it.

**Files:**
- Modify: `src/agentdb/dashboard/static/app.js`

- [ ] **Step 1: Add state and ID generator**

In `app.js`, after the existing state variables (~line 13), add:

```javascript
  var recentActivity = [];
  var activityIdCounter = 0;
  var MAX_ACTIVITY = 50;
  var chipFilter = null;  // service id or null
```

- [ ] **Step 2: Add `pushActivity` helper function**

After the state section, add:

```javascript
  function pushActivity(type, service, agent, summary, severity, tick, detail) {
    activityIdCounter++;
    recentActivity.unshift({
      id: "act-" + activityIdCounter,
      type: type,
      service: service || null,
      agent: agent || null,
      summary: summary,
      severity: severity || "low",
      tick: tick,
      timestamp: Date.now(),
      detail: detail
    });
    if (recentActivity.length > MAX_ACTIVITY) {
      recentActivity.pop();
    }
    renderChipBar();
  }
```

- [ ] **Step 3: Wire 4 message types into `pushActivity`**

In `handleCityEvent` (~line 136), after the existing `addFeedEntry(data)`:

```javascript
    pushActivity(
      "event",
      data.service,
      null,
      data.message || data.event_type,
      data.severity || "low",
      data.tick || 0,
      data
    );
```

In the `agent_message` case (~line 97), after the existing event dispatches:

```javascript
        pushActivity(
          "agent_action",
          msg.data.service || null,
          msg.data.agent,
          (msg.data.agent || "agent") + ": " + (msg.data.message || "").slice(0, 60),
          "low",
          msg.data.tick || 0,
          msg.data
        );
```

In the `code_diff` case (~line 100), after the existing `dispatchEvent`:

```javascript
        var codePath = msg.data.path || "";
        var codeService = null;
        if (codePath.startsWith("/city/services/")) {
          var codeParts = codePath.split("/");
          if (codeParts.length >= 4) codeService = codeParts[3];
        }
        pushActivity(
          "code_change",
          codeService,
          msg.data.agent || null,
          (msg.data.action || "changed") + " " + codePath.split("/").pop(),
          "low",
          msg.data.tick || 0,
          msg.data
        );
```

In the `fs_change` case (~line 103), after the existing `dispatchEvent`:

```javascript
        var fsPath = msg.data.path || "";
        var fsService = null;
        if (fsPath.startsWith("/city/services/")) {
          var fsParts = fsPath.split("/");
          if (fsParts.length >= 4) fsService = fsParts[3];
        }
        pushActivity(
          "fs_change",
          fsService,
          null,
          msg.data.action + " " + fsPath.split("/").pop(),
          "low",
          msg.data.tick || 0,
          msg.data
        );
```

- [ ] **Step 4: Add placeholder `renderChipBar` function**

At the end of the file (inside the IIFE), add:

```javascript
  function renderChipBar() {
    // Implemented in Task 10
  }
```

- [ ] **Step 5: Commit**

```bash
git add src/agentdb/dashboard/static/app.js
git commit -m "feat: add unified recentActivity model with 4 message types"
```

---

### Task 9: Chip bar HTML and CSS

Add the chip bar container to index.html and styles to style.css.

**Files:**
- Modify: `src/agentdb/dashboard/static/index.html:45-48`
- Modify: `src/agentdb/dashboard/static/style.css`

- [ ] **Step 1: Add chip bar container to HTML**

In `index.html`, after the `<canvas>` container div (~line 47), add the chip bar inside `panel-map`:

```html
      <div class="canvas-container">
        <canvas id="cityCanvas"></canvas>
      </div>
      <div class="chip-bar" id="chipBar">
        <div class="chip-bar-filter" id="chipFilter" style="display:none;">
          <span id="chipFilterLabel"></span>
          <button class="chip-filter-clear" id="chipFilterClear">&times;</button>
        </div>
        <div class="chip-bar-chips" id="chipBarChips"></div>
      </div>
```

- [ ] **Step 2: Add chip bar CSS**

In `style.css`, after the `.canvas-container` / `#cityCanvas` section (~line 298), add:

```css
/* ============================================================
   Chip Bar
   ============================================================ */

.chip-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--bg-secondary);
  border-top: 1px solid var(--border-subtle);
  min-height: 32px;
  flex-shrink: 0;
  overflow: hidden;
}

.chip-bar-filter {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 9px;
  color: var(--accent);
  background: var(--bg-primary);
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid var(--accent-dim);
  white-space: nowrap;
  flex-shrink: 0;
}

.chip-filter-clear {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  padding: 0 2px;
}

.chip-filter-clear:hover {
  color: var(--text-primary);
}

.chip-bar-chips {
  display: flex;
  gap: 4px;
  overflow-x: hidden;
  flex: 1;
}

.chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: var(--bg-elevated);
  border-radius: var(--radius-sm);
  border-left: 3px solid var(--severity-low);
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background 0.15s ease;
  animation: chipSlideIn 0.2s ease-out;
  position: relative;
}

@keyframes chipSlideIn {
  from {
    opacity: 0;
    transform: translateX(-8px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.chip:hover {
  background: var(--border);
}

.chip-icon {
  font-size: 10px;
  flex-shrink: 0;
}

.chip-text {
  font-size: 10px;
  color: var(--text-primary);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chip-time {
  font-size: 9px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.chip[data-severity="medium"] { border-left-color: var(--severity-medium); }
.chip[data-severity="high"]   { border-left-color: var(--severity-high); }
.chip[data-severity="critical"] { border-left-color: var(--severity-critical); }

/* Tooltip */
.chip .chip-tooltip {
  display: none;
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: 4px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px 8px;
  font-size: 10px;
  color: var(--text-primary);
  white-space: normal;
  max-width: 300px;
  z-index: 10;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}

.chip:hover .chip-tooltip {
  display: block;
}
```

- [ ] **Step 3: Verify manually**

Open the dashboard. The chip bar should appear as a thin strip below the canvas. No chips yet (renderChipBar is a no-op).

- [ ] **Step 4: Commit**

```bash
git add src/agentdb/dashboard/static/index.html src/agentdb/dashboard/static/style.css
git commit -m "feat: add chip bar HTML structure and CSS styles"
```

---

### Task 10: Render chip bar with interactions

Implement the `renderChipBar` function and wire up chip click, node click filter, and filter clear.

**Files:**
- Modify: `src/agentdb/dashboard/static/app.js`

- [ ] **Step 1: Implement `renderChipBar`**

Replace the placeholder `renderChipBar` function:

```javascript
  var MAX_VISIBLE_CHIPS = 12;

  var CHIP_ICONS = {
    event: "\u26A1",
    agent_action: "\uD83E\uDD16",
    code_change: "\uD83D\uDCDD",
    fs_change: "\uD83D\uDCC2"
  };

  function relativeTime(ts) {
    var diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 60) return diff + "s ago";
    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
    return Math.floor(diff / 3600) + "h ago";
  }

  function renderChipBar() {
    var container = document.getElementById("chipBarChips");
    if (!container) return;

    // Filter by selected service
    var items = chipFilter
      ? recentActivity.filter(function (a) { return a.service === chipFilter; })
      : recentActivity;

    // Show at most MAX_VISIBLE_CHIPS
    var visible = items.slice(0, MAX_VISIBLE_CHIPS);

    // Clear container safely (no innerHTML)
    while (container.firstChild) {
      container.removeChild(container.firstChild);
    }

    for (var i = 0; i < visible.length; i++) {
      var item = visible[i];
      var chip = document.createElement("div");
      chip.className = "chip";
      chip.setAttribute("data-severity", item.severity);
      chip.setAttribute("data-activity-id", item.id);

      var icon = document.createElement("span");
      icon.className = "chip-icon";
      icon.textContent = CHIP_ICONS[item.type] || "\u2022";

      var text = document.createElement("span");
      text.className = "chip-text";
      text.textContent = item.summary.slice(0, 40);

      var time = document.createElement("span");
      time.className = "chip-time";
      time.textContent = relativeTime(item.timestamp);

      // Tooltip
      var tooltip = document.createElement("div");
      tooltip.className = "chip-tooltip";
      tooltip.textContent = item.summary;

      chip.appendChild(icon);
      chip.appendChild(text);
      chip.appendChild(time);
      chip.appendChild(tooltip);

      // Click handler: highlight service on graph (but don't filter chips) + open diff if code_change
      (function (actItem) {
        chip.addEventListener("click", function () {
          if (actItem.service && typeof window.updateServiceNode === "function") {
            // Use source:"chip" so the filter listener knows not to filter
            window.dispatchEvent(new CustomEvent("agentdb:service-selected", {
              detail: { service: actItem.service, label: actItem.service, source: "chip" }
            }));
          }
          if (actItem.type === "code_change" && actItem.detail) {
            window.dispatchEvent(new CustomEvent("agentdb:code-diff", { detail: actItem.detail }));
            window.dispatchEvent(new CustomEvent("agentdb:chip-open-diff", { detail: actItem.detail }));
          }
        });
      })(item);

      container.appendChild(chip);
    }
  }
```

- [ ] **Step 2: Wire node click to chip filter**

After `renderChipBar`, add:

```javascript
  // Listen for service selection to filter chips (only from graph clicks, not chip clicks)
  window.addEventListener("agentdb:service-selected", function (e) {
    // Chip clicks set source:"chip" -- they should highlight the node but not filter
    if (e.detail.source === "chip") return;

    var filterEl = document.getElementById("chipFilter");
    var filterLabel = document.getElementById("chipFilterLabel");

    if (e.detail.service && e.detail.service !== chipFilter) {
      chipFilter = e.detail.service;
      if (filterEl) filterEl.style.display = "flex";
      if (filterLabel) filterLabel.textContent = "Showing: " + e.detail.service;
    } else {
      chipFilter = null;
      if (filterEl) filterEl.style.display = "none";
    }
    renderChipBar();
  });

  // Clear filter button
  var clearBtn = document.getElementById("chipFilterClear");
  if (clearBtn) {
    clearBtn.addEventListener("click", function (evt) {
      evt.stopPropagation();
      chipFilter = null;
      document.getElementById("chipFilter").style.display = "none";
      renderChipBar();
    });
  }

  // Refresh chip timestamps every 10 seconds
  setInterval(renderChipBar, 10000);
```

- [ ] **Step 3: Verify manually**

Open the dashboard:
- Chips appear below the Canvas as events arrive
- Hovering shows a tooltip with full message
- Clicking a chip highlights the relevant node on the graph
- Clicking a node filters chips to that service
- "Showing: X" label appears with a clear button
- Clicking the clear button removes the filter

- [ ] **Step 4: Commit**

```bash
git add src/agentdb/dashboard/static/app.js
git commit -m "feat: implement chip bar rendering with click interactions and filtering"
```

---

### Task 11: Wire chip click to detail panel diff tab

When a chip of type `code_change` is clicked, switch to the diffs tab in the detail panel.

**Files:**
- Modify: `src/agentdb/dashboard/static/detail-tabs.js:27-55`

- [ ] **Step 1: Add event listener for chip-open-diff**

In `detail-tabs.js`, inside the `init` function, after the existing `agentdb:fs-change` listener (~line 53), add:

```javascript
        window.addEventListener("agentdb:chip-open-diff", function () {
          self.tab = "diffs";
        });
```

- [ ] **Step 2: Verify manually**

Click a code_change chip. The detail panel should switch to the Diffs tab.

- [ ] **Step 3: Commit**

```bash
git add src/agentdb/dashboard/static/detail-tabs.js
git commit -m "feat: wire chip click to switch detail panel to diffs tab"
```

---

### Task 12: Run full test suite and verify

Final verification that all backend tests still pass and the visual features work end-to-end.

**Files:**
- No new files

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS (93 existing + 2 new = 95)

- [ ] **Step 2: Manual end-to-end verification**

Start the server: `uv run python main.py`

Check each feature:
1. **Degraded pulse:** Wait for a service to degrade. Node ring should pulse yellow.
2. **Failed shake + glow:** If a service fails, node shakes then glows red.
3. **Recovery flash:** When a service returns to ok, brief green flash.
4. **Cascade edge pulse:** If a cascade fires, red pulse travels along the edge.
5. **Agent presence dots:** When agents act, colored dots appear around the target node.
6. **Chip bar:** Events, agent actions, code changes, and fs changes appear as chips.
7. **Chip hover:** Tooltip shows full message.
8. **Chip click to node highlight:** Clicking a chip highlights the relevant service.
9. **Node click to chip filter:** Clicking a node filters chips. Filter label shows. Clear button works.
10. **Chip click to diff tab:** Clicking a code_change chip opens the diffs tab.

- [ ] **Step 3: Final commit (if any cleanup needed)**

```bash
git add -A
git commit -m "feat: reactive dashboard phase 1 complete"
```
