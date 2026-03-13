# Reactive Dashboard: Visible Agent Behavior

**Date:** 2026-03-12
**Status:** Approved
**Goal:** Make agent behavior visible and compelling by adding reactive graph animations and a unified event chip bar that links graph activity to contextual detail.

**Approach:** Phased delivery (Approach 3 — "Linked Graph + Timeline"). Phase 1 delivers reactive graph + event chip bar. Phase 2 (future) replaces chip bar with full unified timeline.

---

## Section 1: Reactive Graph Enhancements

### Current State

Circular layout with static colored rings, simple flow dots on edges, click-to-select.

### Node Animations by Status Transition

- **ok → degraded:** Node ring pulses yellow (scale oscillation 1.0→1.08, 2s cycle). Inner load arc turns amber.
- **ok/degraded → failed:** Node shakes (horizontal jitter ±3px, 0.5s), then glows red with a soft bloom (radial gradient halo, fades over 3s). Ring turns solid red.
- **failed → ok (recovery):** Brief green flash (0.3s), then settle to normal green ring.
- **idle → agent working on it:** Small colored dot (agent's color) orbits the node. Dot disappears when agent finishes.

### Edge Animations for Cascades

When a cascade event fires, the edge from failed service to affected service lights up: a bright pulse travels along the edge (source → target, 0.4s), then the edge stays highlighted red for 2s before fading back to gray.

Multiple cascades chain visually — the pulse ripples outward through the dependency graph.

### Agent Presence

Each agent gets a small colored indicator (8px circle) positioned around the node they're currently acting on (derived from `agent_message` events with tool calls targeting that service).

When an agent hands off, the dot slides from one node to another (lerp over 0.3s).

### Implementation

All changes in `graph.js`. Extend the existing render loop with a transition state per node/edge. No new files needed. WebSocket messages already carry the required data: `tick` has status, `city_event` has cascades, `agent_message` has service context.

---

## Section 2: Event Chip Bar

### Purpose

A lightweight bridge between the graph and detailed information. Shows recent activity as clickable chips at the bottom of the graph panel — enough context to understand what's happening without switching tabs.

### Layout

Horizontal strip below the Canvas, max 8 chips visible, newest on the right. Overflow scrolls left (older chips slide out). When nothing is happening, the bar is a thin quiet line.

### Chip Anatomy

- **Left edge:** 3px color bar (severity or agent color)
- **Icon:** Small glyph per type — ⚡ event, 🤖 agent action, 📝 code change
- **Text:** One-line summary truncated at ~40 chars (e.g., "fixer patched power-grid/main.py")
- **Timestamp:** Relative ("4s ago")

### Chip Sources (unified from currently separate streams)

- `city_event` → "power-grid failed" / "cascade hit water-system"
- `agent_message` with tool calls → "monitor created incident INC-12" / "fixer patched main.py"
- `code_diff` → "engineer wrote traffic-control/main.py"

### Interactions

- **Hover chip** → tooltip with full message text
- **Click chip** → highlights the relevant service node on the graph (glow). If it's a code diff, also opens the diff in the detail panel below.
- **Click service node** → filters chips to only that service (toggle behavior, click again to unfilter)

### Data Model

A single `recentActivity[]` array in `app.js` that all three message types push into, with a unified shape (see Section 3). This same array becomes the data source for the full timeline in phase 2.

---

## Section 3: Graph-Timeline Linking (Phase 2 Contract)

Defines the interface between phase 1 and phase 2 so the event chip bar evolves cleanly into a full timeline.

### Unified Activity Model

```javascript
{
  id: string,          // unique per event
  type: "event" | "agent_action" | "code_change" | "fs_change",
  service: string | null,
  agent: string | null,
  summary: string,
  severity: "info" | "medium" | "high" | "critical",
  tick: number,
  timestamp: number,
  detail: object       // raw payload for expansion
}
```

### Phase 2 Scope (future)

Replaces chip bar with a full timeline panel:
- Vertical scrollable list (replaces the current activity feed and conversations tab — single source of truth)
- Filter buttons: by type, by service, by agent
- Expandable rows: click to see full agent message, diff view, or event detail inline
- Bidirectional linking: click node → filter timeline to that service, click timeline entry → highlight node on graph

### What Phase 1 Must Get Right

1. The `recentActivity[]` array uses the unified shape above (not chip-specific)
2. Node click dispatches a custom event (`agentdb:service-selected`) that any component can listen to
3. Agent presence tracking maps agent → service (so timeline entries can be associated with graph nodes)

### What Phase 1 Does NOT Build

- No filtering UI beyond click-to-filter on nodes
- No expandable rows
- No persistence or history beyond the last ~50 items in memory

---

## Section 4: Implementation Boundaries

### Changes Per File

| File | Changes |
|------|---------|
| `graph.js` | Node transition states (pulse/shake/glow), edge cascade animation, agent presence dots, node click emits `agentdb:service-selected` event |
| `app.js` | Unified `recentActivity[]` array, merge 3 message types into it, render chip bar, wire chip click → graph highlight |
| `style.css` | Chip bar styles, chip anatomy, hover tooltip, active/filtered states |
| `index.html` | Chip bar container div below the Canvas |
| `detail-tabs.js` | Listen for chip clicks that target diffs → switch to diffs tab and scroll to entry |

### What Does NOT Change

- `app.py` / `broadcast.py` — no backend changes, all data already available via existing WebSocket messages
- `engine.py` / `runner.py` — no simulation or agent changes
- Existing tab panel stays as-is (chip bar is additive, not a replacement yet)

### Testing Approach

- Manual visual testing (Canvas animations aren't unit-testable)
- Browser dev console: verify custom events fire correctly

---

## Section 5: Phasing and Delivery

### Phase 1 (this design cycle)

1. Reactive graph — node status animations, cascade edge pulses, agent presence dots
2. Event chip bar — unified activity stream, clickable chips, node↔chip linking
3. `agentdb:service-selected` custom event wired up for future timeline use

### Phase 2 (future design cycle)

- Full unified timeline replacing chip bar + activity feed + conversations tab
- Filter/search UI
- Expandable inline detail (diffs, full agent messages)
- Bidirectional graph↔timeline linking

### Phase 1 Success Criteria

- When a service degrades/fails, you can see it happen on the graph without reading any text
- When a cascade fires, you can watch it ripple through edges
- You can tell which agent is working on which service at a glance
- The chip bar gives you enough context to follow the story without switching tabs
