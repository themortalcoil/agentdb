# AgentDB

Multi-agent city simulation backed by a SQLite virtual filesystem (AgentFS). LLM agents (mayor, engineer, monitor, fixer) operate over the same DB via LangGraph Swarm; a simulation engine drives demand and service failures; a FastAPI dashboard streams state and events over WebSockets.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Ollama with models used by agents (e.g. `glm-5:cloud`, `qwen3.5:cloud`) for full agent support; the app runs without them in a degraded mode.

## Setup

```bash
uv sync
# or: pip install -e .
```

Optional dev deps (pytest, httpx):

```bash
uv sync --all-extras dev
```

## Run

```bash
uv run python main.py
# Dashboard: http://0.0.0.0:8000
```

Environment:

- `AGENTDB_DB` — SQLite path (default: `city.db`)
- `TICK_INTERVAL` — seconds between simulation ticks (default: `5`)
- `AGENTDB_HOST` / `AGENTDB_PORT` — dashboard bind (default: `0.0.0.0:8000`)

## Test

```bash
uv run pytest tests/ -v
```

## Layout

| Area | Purpose |
|------|---------|
| `main.py` | Entry: DB init, seed, engine, swarm, runner, FastAPI, tick loop |
| `src/agentdb/config.py` | Env config (DB path, tick interval, host/port) |
| `src/agentdb/seed.py` | Default service code and initial KV/FS seeding |
| `src/agentdb/db/` | Schema, VirtualFS, KVStore, OverlayFS, AuditLog |
| `src/agentdb/simulation/` | ServiceGraph, SimulationEngine, events, ServiceEvaluator |
| `src/agentdb/agents/` | AgentConfigs, CityTools, swarm build, AgentRunner |
| `src/agentdb/dashboard/` | Broadcaster, FastAPI app, static UI |

Design notes: **AgentRunner** runs one orchestration cycle per tick (triage → LLM plan → dispatch). **CityTools** is the single tool layer for agents; attribution flows via `set_current_agent()` into the audit log and event buffer. Specs and plans live under `docs/superpowers/`.
