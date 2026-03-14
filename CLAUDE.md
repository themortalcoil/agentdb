# AgentDB — context for AI assistants

Multi-agent city simulation: SQLite-backed AgentFS + KV store, simulation engine, LangGraph Swarm agents (mayor, engineer, monitor, fixer), FastAPI dashboard with WebSocket events.

## Commands

- **Run:** `uv run python main.py` (dashboard http://0.0.0.0:8000)
- **Tests:** `uv run pytest tests/ -v`
- **Config:** `AGENTDB_DB`, `TICK_INTERVAL`, `AGENTDB_HOST`, `AGENTDB_PORT`

## Architecture (where to change what)

- **DB / persistence:** `src/agentdb/db/` — `schema.py` (tables), `filesystem.py` (VirtualFS), `kvstore.py`, `overlay.py` (staging overlay), `audit.py` (tool_calls).
- **Simulation:** `src/agentdb/simulation/` — `deps.py` (ServiceGraph), `engine.py` (tick loop, demand, evaluation, events), `events.py` (event types, demand curve), `evaluator.py` (runs service `handle_load` in subprocess).
- **Agents:** `src/agentdb/agents/` — `definitions.py` (AgentConfig per role), `tools.py` (CityTools: read/write FS, KV, incidents, staging), `swarm.py` (builds LangGraph Swarm from configs), `runner.py` (orchestration: triage → plan → dispatch, broadcasts).
- **App entry:** `main.py` wires DB, seed, engine, broadcaster, swarm, AgentRunner, FastAPI; `config.py` and `seed.py` hold env and default service code.
- **Dashboard:** `src/agentdb/dashboard/` — `broadcast.py` (WebSocket pub), `app.py` (FastAPI + `/api/state`, `/api/file`, `/api/audit`, `/api/topology`, `/ws`).

## Conventions

- All agent path access must be under `/city/` (enforced in CityTools).
- Service code lives in `/city/services/<name>/main.py` and `config.json`; evaluator runs `handle_load(load, config)` in a sandbox.
- Agent attribution: `CityTools.set_current_agent(name)` before dispatch; audit and event buffer use it.
- Tests: `conftest.py` provides `db` (in-memory SQLite + schema). Async tests use `async def`; pytest-asyncio is in base deps.

## Specs / plans

- `docs/superpowers/specs/` — design specs; `docs/superpowers/plans/` — implementation plans (e.g. agent orchestration, reactive dashboard).
