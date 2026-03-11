# AgentDB: "The City" — Design Specification

**Date**: 2026-03-10
**Status**: Approved
**Type**: Showcase / Portfolio project

## Overview

A living simulated city where LLM-powered agents manage infrastructure services by writing real Python code into a Turso AgentFS SQLite database. Services succeed or fail based on the code agents write. A web dashboard shows the city map, agent activity, service health, and incident timelines in real-time. Users can pause, inject events, and override priorities at any time.

## Tech Stack

- **Language**: Python 3.11+
- **Agent orchestration**: LangGraph Swarm (handoff-based multi-agent)
- **Database**: SQLite with Turso AgentFS schema (Turso cloud as future option)
- **LLM providers**: Ollama cloud — GLM-5 (reasoning), MiniMax M2.5 (coding)
- **Web**: FastAPI + WebSocket backend, vanilla JS + CSS Grid + Canvas frontend
- **Build**: justfile

## Architecture

Four layers:

```
┌─────────────────────────────────────┐
│         Web Dashboard (FastAPI)     │  Real-time city view, agent activity, intervention
├─────────────────────────────────────┤
│       Simulation Engine             │  Event loop: citizens generate load, incidents emerge
├─────────────────────────────────────┤
│       Agent Swarm (LangGraph)       │  Mayor, Engineers, Monitor, Fixer — handoff via swarm
├─────────────────────────────────────┤
│       AgentFS (SQLite)              │  Virtual filesystem, KV store, tool call audit trail
└─────────────────────────────────────┘
```

- **Simulation Engine**: Deterministic tick loop (configurable interval, default 5s). Advances city clock, updates citizen demand, evaluates service code, rolls random events, pushes state to KV store, emits events via WebSocket.
- **Agent Swarm**: LangGraph Swarm with handoff tools. Agents read/write AgentFS. Each agent action persisted in tool_calls table.
- **Web Dashboard**: FastAPI WebSocket streams agent activity and city state. Vanilla JS frontend with Canvas dependency graph.
- **LLM Routing**: MiniMax M2.5 for coding agents (Engineer, Fixer). GLM-5 for reasoning agents (Mayor, Monitor).

## Agent Roles

| Agent | LLM | Tools | Hands off to |
|-------|-----|-------|-------------|
| **Mayor** | GLM-5 | `read_city_state`, `set_priority`, `assign_task` | Engineer, Monitor |
| **Engineer** (x2-3) | MiniMax M2.5 | `write_file`, `read_file`, `deploy_staging`, `run_tests` | Mayor (review), Fixer (test failure) |
| **Monitor** | GLM-5 | `read_metrics`, `check_health`, `create_incident` | Fixer, Mayor |
| **Fixer** | MiniMax M2.5 | `read_file`, `patch_file`, `hotfix_prod`, `rollback` | Monitor (resolved), Mayor (can't fix) |
| **Citizens** | *not agents* | — | Statistical noise generators in simulation engine |

### Handoff Flows

1. **Build flow**: Mayor assigns feature -> Engineer writes code to staging overlay -> Engineer runs tests -> Mayor reviews -> promote to prod (base filesystem)
2. **Incident flow**: Monitor detects anomaly -> creates incident -> Fixer diagnoses -> patches/rollbacks -> Monitor confirms resolution
3. **Escalation**: Fixer can't resolve -> escalates to Mayor -> Mayor may reassign or reprioritize

## Data Model — AgentFS Mapping

### Virtual Filesystem: City Services as Code

```
/city/
├── services/
│   ├── power-grid/
│   │   ├── main.py          # Service logic (executed by simulation engine)
│   │   ├── config.json      # Service configuration
│   │   └── health.json      # Latest health check result
│   ├── water-system/
│   ├── traffic-control/
│   └── comms-network/
├── incidents/
│   ├── INC-001.json
│   └── INC-002.json
└── plans/
    ├── TASK-001.md
    └── TASK-002.md
```

Agents write real Python into the filesystem. The simulation engine imports and calls each service's `main.py` to determine service behavior. Buggy code = service failure.

### KV Store: City & Agent State

| Key pattern | Purpose | Example |
|------------|---------|---------|
| `city:population` | City-wide metrics | `"12500"` |
| `city:budget` | Resource constraints | `"84000"` |
| `service:{name}:status` | Service health | `"degraded"` |
| `service:{name}:load` | Current demand | `"0.87"` |
| `agent:{name}:energy` | Agent fatigue model | `"72"` |
| `agent:{name}:mood` | Agent personality state | `"frustrated"` |
| `agent:{name}:specialty` | Skill weighting | `"networking"` |
| `incident:active_count` | Open incident tracking | `"3"` |
| `mayor:priority` | Current city focus | `"reliability"` |

Agent energy/mood affects decision quality (fatigued Fixer proposes quick patches over proper fixes).

### Tool Calls: Audit Trail

Every agent action stored with name, parameters, result, timing. Dashboard replays these as a timeline.

### Overlay Filesystem: Staging vs Production

| Concept | AgentFS mechanism |
|---------|------------------|
| **Production** | Base filesystem (`fs_inode`, `fs_data`) |
| **Staging** | Overlay layer — writes to overlay, reads check overlay then fall through to base |
| **Deploy to prod** | Merge overlay deltas into base, clear overlay |
| **Rollback** | Discard overlay (delete `fs_origin` and `fs_whiteout` entries) |
| **Delete in staging** | `fs_whiteout` masks base file without removing it |

## Simulation Engine

### Tick Loop

```
Every tick (configurable, default 5s):
  1. Advance city clock (simulated time, faster than real-time)
  2. Update citizen demand per service (sine wave + noise for daily patterns)
  3. Evaluate each service's code against its current load
     → no code or broken code = failure
     → under capacity = degraded
  4. Roll for random events (pipe burst, power surge, traffic jam)
  5. Push state changes to KV store
  6. Emit events to agent swarm + dashboard via WebSocket
```

### Service Evaluation

```python
# Engine calls each service:
result = service_module.handle_load(current_load, config)
# Returns: { "status": "ok"|"degraded"|"failed", "capacity": float, "metrics": dict }
```

### Event Types

| Event | Trigger | Severity | Responder |
|-------|---------|----------|-----------|
| `demand_spike` | Load exceeds capacity | Medium | Monitor -> Engineer |
| `service_failure` | Code error or crash | High | Monitor -> Fixer |
| `infrastructure_decay` | Random, time-based | Low | Monitor -> Mayor -> Engineer |
| `citizen_complaint` | Sustained degradation | Low | Mayor (reprioritizes) |
| `cascade_failure` | Dependency chain failure | Critical | Mayor -> all hands |
| `budget_shortfall` | Too many services | Medium | Mayor (tradeoffs) |

### Service Dependencies

```
comms-network ──> traffic-control
     │                  │
     v                  v
power-grid <──── water-system
```

A power grid failure cascades into water and comms.

## Web Dashboard

### Layout: Four Panels + Timeline

| Panel | Content | Data source |
|-------|---------|-------------|
| **City Map** | Service nodes as dependency graph, color-coded by health (green/yellow/red). Animated edges on cascade. Click to inspect. | KV store changes via WebSocket |
| **Agent Activity Feed** | Real-time stream of agent decisions, handoffs, file writes. Each entry links to tool_calls row. | tool_calls inserts via WebSocket |
| **Agent Status** | Each agent: LLM, energy bar, mood, current task. Handoff arrows on transfers. | KV store agent keys via WebSocket |
| **Service Detail** | Selected service: load chart, incident history, staging overlay diff, code preview. | On node click |
| **Timeline** (bottom) | Scrollable horizontal timeline of incidents and tasks. Click to jump. | Incident/task records |

### Intervention Controls

| Control | Effect |
|---------|--------|
| Pause/Resume | Stops tick loop, agents freeze |
| Inject Event | Trigger any event type on any service |
| Override Priority | Text sent to Mayor as system message |
| Speed slider | Tick interval: 1s (fast) to 30s (slow) |
| Agent kill switch | Disable individual agent |

### Tech

- FastAPI + WebSocket endpoint
- SQLite change hooks to detect DB mutations
- Vanilla JS + CSS Grid + Canvas (dependency graph with animated edges)
- CSS bars for load meters

## Error Handling

| Failure mode | Response |
|---|---|
| LLM returns invalid code | Simulation engine catches errors, service -> `failed`, Fixer gets incident |
| LLM refuses/hallucinates | Tool functions validate inputs (paths under `/city/`, JSON must parse). Retry up to 3 times |
| Agent stuck in loop | Tick counter: >5 actions without resolution -> escalate to Mayor |
| Ollama cloud unreachable | Pause tick loop, surface to dashboard |
| SQLite write contention | WAL mode + single-writer architecture |
| Cascade spiral | Circuit breaker: >3 simultaneous failures -> Mayor enters emergency mode |

## Testing

| Layer | Method |
|---|---|
| AgentFS operations | Unit tests against in-memory SQLite |
| Simulation engine | Deterministic tests with fixed random seeds |
| Agent tools | Unit tests with mock filesystem state |
| Agent swarm | Scenario tests with recorded LLM responses |
| Dashboard | Manual + WebSocket message tests |

## Explicit Non-Goals

- No persistent city across restarts (fresh each run)
- No multi-user dashboard (single viewer)
- No real container deployments (simulated services)
- No agent learning across sessions (standalone runs)
- No authentication on dashboard
- Citizens are statistical generators, not individual actors
