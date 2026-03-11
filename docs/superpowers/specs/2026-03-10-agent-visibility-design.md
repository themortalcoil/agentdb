# Agent Visibility — Design Spec

## Goal

Surface agent work (conversations, code diffs, filesystem changes) in the dashboard through a tabbed detail panel, making the AgentFS-driven simulation observable and interactive.

## Architecture

Extend the existing WebSocket broadcast pipeline with new message types. Server-side, CityTools captures file-change events in a buffer during each swarm cycle. After the swarm returns, `run_agents()` walks the full LangGraph message history to extract agent conversations, correlates them with the buffered file changes (adding agent attribution), and broadcasts everything. An Alpine.js-powered tabbed panel replaces the current Service Detail panel.

## Layout

The bottom "Service Detail" panel expands from `max-height: 140px` to ~40% of the viewport. The top grid (service map, activity feed, agent status) shrinks proportionally.

The expanded panel has 4 tabs:
- **Conversations** — linear chat log of agent messages per swarm cycle
- **Code Diffs** — unified diffs when agents write/patch service code
- **Filesystem** — live tree view of the VirtualFS with flash-on-change highlights
- **Service Detail** — existing service detail view, moved into a tab

Cross-linking: clicking an agent status card switches to Conversations; clicking a code-related feed item switches to Code Diffs.

## New WebSocket Message Types

### `agent_message`

Emitted for each agent response in a swarm cycle.

```json
{
  "type": "agent_message",
  "data": {
    "cycle_id": 12,
    "tick": 47,
    "agent": "fixer",
    "message": "Reading power-grid/main.py...",
    "tools_used": ["read_file", "patch_file", "hotfix_prod"],
    "handoff_to": "monitor"
  }
}
```

### `code_diff`

Emitted when an agent writes or patches a file through CityTools.

```json
{
  "type": "code_diff",
  "data": {
    "tick": 47,
    "agent": "fixer",
    "path": "/city/services/power-grid/main.py",
    "old_content": "...",
    "new_content": "...",
    "action": "hotfix_prod"
  }
}
```

### `fs_change`

Emitted on any VirtualFS write or delete.

```json
{
  "type": "fs_change",
  "data": {
    "tick": 47,
    "path": "/city/incidents/INC-003.json",
    "action": "write",
    "size": 142,
    "agent": "monitor"
  }
}
```

### `fs_snapshot`

Sent once when a WebSocket client connects. Provides the full directory tree so the filesystem browser populates immediately.

```json
{
  "type": "fs_snapshot",
  "data": {
    "tree": {
      "city": {
        "services": {
          "power-grid": {"main.py": 245, "config.json": 22},
          "water-system": {"main.py": 245, "config.json": 22}
        },
        "incidents": {"INC-001.json": 156}
      }
    }
  }
}
```

**Tree schema:** A nested dict where keys are entry names. If the value is an integer, it represents a file with that byte size. If the value is a dict, it represents a directory containing the nested entries. This rule applies recursively.

## Server-Side Changes

### CityTools event buffer

`CityTools.__init__` accepts an optional `event_buffer: list`. Tool methods append event dicts to this list after successful operations. The buffer does NOT include agent names — CityTools is shared across all agents and has no knowledge of which agent is calling it.

Each tool captures before/after state as needed:

- `write_file`: reads existing content BEFORE writing, appends `{"type": "code_diff", "path": ..., "old_content": ..., "new_content": ..., "action": "write"}` and `{"type": "fs_change", "path": ..., "action": "write", "size": ...}`
- `patch_file`: reads from overlay (which falls through to base if no overlay version exists) BEFORE writing to overlay, appends `code_diff` with `action: "stage"` and `fs_change`
- `hotfix_prod`: calls `overlay.list_changes()` BEFORE calling `overlay.merge()`. For each modified file, reads both the overlay version and the base version to build a `code_diff` with `action: "merge"`. Emits `fs_change` for each merged file.
- `rollback`: calls `overlay.list_changes()` BEFORE calling `overlay.discard()`. Emits `fs_change` with `action: "delete"` for each discarded file.
- `create_incident`: emits `fs_change` for the incident JSON file
- `assign_task`: emits `fs_change` for the task JSON file

### run_agents() — post-cycle broadcast

After `swarm.ainvoke()` returns, `run_agents()` does two things:

**1. Walk the message history to extract `agent_message` events.** Iterate `result["messages"]` and identify agent responses:

- LangGraph messages have a `type` attribute. `AIMessage` (from `langchain_core.messages`) represents agent responses.
- `AIMessage.name` gives the agent name (e.g., `"fixer"`, `"monitor"`).
- `AIMessage.tool_calls` is a list of dicts with `{"name": "tool_name", ...}`. Extract tool names from here.
- Handoff tools are named `transfer_to_<agent>` (created by `langgraph_swarm.create_handoff_tool`). If a tool call matches this pattern, extract the target agent name as `handoff_to`.
- `AIMessage.content` is the agent's text response. Skip messages with empty content (pure tool-call messages without text).

**2. Enrich and broadcast buffered file events.** Read the `event_buffer` list, add `tick` and `agent` fields to each event. Agent attribution: correlate by walking the message history — the most recent agent that called a file-writing tool owns the corresponding buffer entries. Broadcast each as `code_diff` or `fs_change`. Clear the buffer.

A monotonically increasing `cycle_id` (counter on the module level) groups all messages and events from the same swarm invocation.

### build_swarm — buffer threading

`main.py` creates the `event_buffer` list and passes it to `build_swarm`, which passes it to `CityTools`. Since the swarm runs in a single `ainvoke()` call, the buffer accumulates all events from that cycle. `run_agents()` reads and clears it after each cycle.

### WebSocket connect snapshot

In `app.py`, when a new WebSocket connects, build a directory tree by recursively walking VirtualFS from root using `list_dir()` and `read_file()` (to check file vs directory). Send the tree as an `fs_snapshot` message before entering the broadcast loop. The VirtualFS instance is passed to `create_app()` for this purpose.

## Frontend Changes

### Alpine.js integration

Add Alpine.js via CDN (`<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3/dist/cdn.min.js">`). The tabbed detail panel is an Alpine component.

### Custom DOM events (app.js → detail-tabs.js bridge)

`app.js` dispatches these `CustomEvent`s on `window`:

| WebSocket message type | Custom event name | `event.detail` payload |
|------------------------|-------------------|------------------------|
| `agent_message` | `agentdb:agent-message` | The `data` object from the WebSocket message |
| `code_diff` | `agentdb:code-diff` | The `data` object from the WebSocket message |
| `fs_change` | `agentdb:fs-change` | The `data` object from the WebSocket message |
| `fs_snapshot` | `agentdb:fs-snapshot` | The `data` object from the WebSocket message |

`detail-tabs.js` listens for these events and updates Alpine reactive state.

### File changes

**`index.html`**
- Add Alpine.js CDN script tag (before `detail-tabs.js`, with `defer`)
- Restructure detail panel with Alpine directives (`x-data="detailPanel"`, `x-show`, `@click`, `x-for`)
- Remove existing service detail DOM (replaced by Alpine template in Service Detail tab)

**`detail-tabs.js`** (new file)
- Defines the `detailPanel` Alpine data function
- Manages reactive state: `tab`, `conversations[]`, `diffs[]`, `fsTree{}`, `serviceDetail{}`
- Listens for `agentdb:*` custom events on `window`
- Handles cross-linking (agent card click -> conversations tab)
- Exposes `window.selectService` replacement that updates Alpine state AND switches to the Service Detail tab

**`app.js`**
- Add `case "agent_message"`, `case "code_diff"`, `case "fs_change"`, `case "fs_snapshot"` to `handleMessage` switch
- Each dispatches the corresponding `agentdb:*` custom event with the data payload
- Existing tick/event/agent_update handlers unchanged
- Remove the existing `window.selectService` definition (moved to `detail-tabs.js`)

**`graph.js`**
- No changes. It calls `window.selectService(...)` which is now defined by `detail-tabs.js` instead of `app.js`. The function signature stays the same: `selectService(name, status, load, capacity)`.

**`style.css`**
- Tab bar styles (active tab highlight matching `--accent` color, hover states)
- Conversation card styles (colored left border per agent, tool tags as inline badges)
- Diff styles (red/green line coloring with `--status-failed`/`--status-ok`, file path header, collapsible via `details`/`summary`)
- Tree view styles (indentation via `padding-left`, directory expand/collapse, file size in `--text-muted`)
- Flash animation keyframes: `@keyframes fs-flash-write` (yellow pulse) and `@keyframes fs-flash-delete` (red pulse)

### Tab view details

**Conversations**
- Messages grouped by cycle with separator label ("Tick 47 — Cycle #12")
- Each message card: colored left border (agent color), agent name, content (truncated to 3 lines, expand on click), tool tags as small inline badges, handoff arrow if present
- Auto-scroll to newest unless user has scrolled up (check `scrollTop` vs `scrollHeight`)
- Retain max 50 cycles, oldest pruned

**Code Diffs**
- Unified diff with red/green line coloring
- Header: file path, agent, tick, action (stage/merge/write)
- Newest first, each collapsible via `<details>/<summary>`
- Line-by-line diff computed client-side: split old/new content by newlines, compare line-by-line, prefix removed lines with `-`, added lines with `+`, unchanged with space
- Retain max 20 diffs

**Filesystem**
- Indented tree built from `fs_snapshot` on connect, updated by `fs_change` messages
- Directories collapsible (click to toggle), files show size in bytes
- Click a file to fetch its contents via `GET /api/file?path=...` and display in a read-only `<pre>` pane on the right side of the tab
- When `fs_change` arrives with `action: "write"`, apply `fs-flash-write` animation (yellow pulse, 1.5s) to the affected tree node
- When `fs_change` arrives with `action: "delete"`, apply `fs-flash-delete` animation (red pulse, 1.5s) then remove the node
- Tree sorted alphabetically, directories before files

**Service Detail**
- Existing service detail view, moved into the Alpine component
- `window.selectService` (redefined in `detail-tabs.js`) updates Alpine reactive state and switches to this tab
- Shows: service name, status (colored), load %, capacity %, headroom % — same layout as current

## New REST Endpoint

**`GET /api/file?path=/city/services/power-grid/main.py`**

Returns file contents from VirtualFS as plain text (`Content-Type: text/plain; charset=utf-8`). Used by the filesystem browser when a user clicks a file.

- `200 OK` with file contents as body
- `404 Not Found` with `{"error": "File not found"}` if the path does not exist in VirtualFS
- Path must start with `/city/` (validated server-side, returns `400` otherwise)

## Constraints

- No build step. Alpine.js via CDN, vanilla JS for everything else.
- Canvas rendering (graph.js) unchanged.
- Existing WebSocket message types (tick, city_event, agent_update) unchanged.
- All new JS in `detail-tabs.js` to minimize changes to existing files.
