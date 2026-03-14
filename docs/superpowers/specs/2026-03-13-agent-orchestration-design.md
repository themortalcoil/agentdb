# Agent Orchestration: Attribution, Deploy Pipeline, and Hybrid Planner

**Date:** 2026-03-13
**Status:** Approved
**Goal:** Fix agent attribution in audit logs, ensure agents complete the full deploy pipeline, and add a hybrid orchestrator that routes work intelligently.

**Approach:** Hybrid orchestrator — deterministic triage identifies problems (fast, free), LLM planner generates targeted task instructions when there's actionable work, agents execute with explicit workflow steps.

---

## Section 1: Agent Attribution

### Current Problem

`CityTools` is a shared singleton across all agents. When an agent calls `write_file`, `AuditLog.track()` records `agent_name=None` because it has no way to know which agent made the call. This means:
- Audit log entries have no agent attribution
- Dashboard can't show which agent performed which action
- Event buffer entries (WebSocket broadcasts) lack agent identity

### Fix: set_current_agent + Audit Row ID Collection

**`tools.py` changes:**
- Add `_current_agent: str | None` field and `set_current_agent(name: str | None)` method
- `_audit_ctx` passes `self._current_agent` to `track()` as `agent_name`
- `_audit_ctx` stores the inserted audit row ID on a `_recent_audit_ids: list[int]` collector (appended in the `finally` block of `track()`)
- `_emit()` includes an `agent` field (value of `_current_agent`)
- Add `pop_audit_ids() -> list[int]` method — returns and clears `_recent_audit_ids`

**`audit.py` changes:**
- Add `agent_name` parameter to `track()` context manager (default `None` for backward compatibility)
- Inside `track()`'s `finally` block, capture `cursor.lastrowid` and store it on the `ToolCallTracker` as `row_id`
- The caller (`_audit_ctx`) reads `tracker.row_id` after the context manager exits and appends to `_recent_audit_ids`

**`runner.py` changes:**
- Before dispatching each agent task, call `city_tools.set_current_agent(agent_name)`
- This means both audit rows AND event buffer entries get the correct agent name during execution
- After each dispatch, call `city_tools.pop_audit_ids()` to get the row IDs (for logging/debugging; attribution is already set during execution)

**Wiring: runner needs access to `city_tools`:**
- `build_swarm()` in `swarm.py` currently creates `CityTools` as a local variable. Change it to return `(compiled_swarm, city_tools)` as a tuple.
- `main.py` unpacks the tuple and passes `city_tools` to `AgentRunner.__init__` as a new parameter.
- `AgentRunner` stores `self._city_tools` for use in `set_current_agent` calls.

**Why set_current_agent works (no retroactive needed):**
- The runner calls `set_current_agent(agent_name)` before each dispatch
- LangGraph runs agents sequentially within `ainvoke` — tool calls happen during execution
- `track()` receives the agent name at call time, writes it to the DB row immediately
- No post-hoc matching needed

### Thread Safety

LangGraph runs agents sequentially within a single `ainvoke`. No concurrent tool execution, so `_current_agent` as shared mutable state is safe.

---

## Section 2: Hybrid Orchestrator

### Current Problem

`run_cycle()` sends a generic "Tick N. Check city health." prompt to the entire swarm every cycle. Agents get no specific instructions, don't know what's broken, and frequently fail to complete the deploy pipeline (stage → test → hotfix).

### Three-Phase Cycle

Replace the current single-phase cycle with:

**Phase 1: Deterministic Triage (code, no LLM)**

Read KV state and build a structured picture:
- Which services are failed/degraded/ok
- Current load vs capacity per service
- Recent incidents: scan `/city/incidents/` files, consider incidents "stale" if created more than 10 ticks ago (triage ignores stale incidents to avoid perpetual re-dispatching; there is no incident close mechanism)
- What agents attempted last cycle and whether it worked

If everything is ok — no failed or degraded services, no recent incidents — broadcast idle status for all agents. No LLM calls. This is the "lightweight check" that runs every cycle.

**Triage needs KV and FS access.** The runner receives `kv` and `fs` as new constructor parameters (see wiring changes in Section 4).

**Phase 2: LLM Planner (one call when there's work)**

If triage found actionable work, call the planner with a structured state summary. The planner returns a JSON plan: which agents to dispatch, what each should do.

The planner is NOT a swarm agent. It's a direct `ChatOllama` call to `glm-5:cloud` (reasoning model) that returns structured JSON. No tools, no handoffs.

The planner prompt bakes in deploy workflow knowledge so it instructs agents to complete all steps.

**Phase 3: Targeted Agent Dispatch**

For each task in the plan, invoke the swarm with a targeted prompt containing the specific instruction from the planner. Agents get told exactly what to do, including the full pipeline steps.

### Planner Prompt

```
You are the city operations planner. Given the current city state, decide which agents to dispatch and what each should do.

Rules:
- Only dispatch agents when there's actionable work
- Fixer handles failed services (must complete: read → patch → hotfix_prod)
- Engineer handles degraded services or capacity improvements (must complete: read → deploy_staging → run_tests → hand off to fixer for hotfix)
- Monitor creates incidents for untracked failures
- Mayor sets priorities when multiple services need attention
- Never dispatch an agent without a specific instruction

Current state:
{triage_summary}

Previous cycle results:
{last_plan_results}

Respond with JSON only: {"tasks": [{"agent": "...", "instruction": "..."}]}
```

### Dispatch Strategy

Each task from the planner becomes a separate `ainvoke` call with a fresh `thread_id` (e.g., `f"cycle-{cycle}-{task_index}"`). This prevents conversation history from growing unbounded across cycles. The targeted prompt contains all the context the agent needs — no prior conversation required.

The swarm's handoff mechanism still works within a single dispatch — if the planner dispatches engineer, and engineer hands off to fixer within that `ainvoke`, fixer runs in the same call. The planner should prefer dispatching the entry-point agent and letting the swarm chain handle multi-agent workflows (e.g., dispatch engineer who hands off to fixer for hotfix, rather than dispatching them separately).

### Planner Failure Handling

If the planner LLM call fails (timeout, connection error) or returns malformed JSON, the cycle falls back to the current generic prompt: `"Tick N. Check city health..."` via a single swarm `ainvoke`. This ensures agents still run even when the planner is unavailable.

### Cycle Tracking

The runner keeps `_last_plan` (the plan) and `_last_results` (what happened) so the planner can see what was attempted last cycle and adjust. If a service is still failed after a fix attempt, the planner can try a different approach.

### Changes

- `runner.py` — rewrite `run_cycle()` with three phases; add `_triage()`, `_plan()`, `_dispatch()` methods; add planner prompt template; add `_last_plan` / `_last_results` tracking; new `ChatOllama` import for planner model

---

## Section 3: Agent Prompt Improvements

### Current Problem

Agent system prompts describe roles but don't enforce the deploy workflow. Agents frequently stage code without calling `hotfix_prod`, leaving fixes stuck in the overlay while the evaluator reads stale production code.

### Updated Prompts

**Engineer:**
```
You are a City Engineer. You write Python code for city services.
Each service has a main.py with a handle_load(load, config) function:
  Returns {'status': 'ok'|'degraded'|'failed', 'capacity': float, 'metrics': dict}

Workflow (follow ALL steps in order):
1. read_file to see current code and config.json
2. Write improved code via deploy_staging
3. run_tests to verify it compiles
4. If tests pass: hand off to fixer to run hotfix_prod
5. If tests fail: fix and retry from step 2

CRITICAL: Code in staging does nothing until hotfix_prod merges it to production.
Never skip steps. Write clean, efficient Python. Higher capacity handles more load.
```

**Fixer:**
```
You are the City Fixer. You diagnose and fix broken services.

Workflow (follow ALL steps in order):
1. read_file to see the failing service's code and config.json
2. patch_file with the fix
3. hotfix_prod to merge staging to production
4. Hand off to monitor to verify resolution

CRITICAL: Always call hotfix_prod after patching. Staged code does nothing until merged.
If you can't fix it, rollback and escalate to mayor. Fix root causes, not symptoms.
```

**Monitor:**
```
You are the City Monitor. You watch service health and detect anomalies.

Responsibilities:
1. check_health to see all service statuses
2. read_metrics for services showing issues
3. create_incident for failures without existing incidents
4. Hand off to fixer for service failures, mayor for strategic decisions

Only create an incident if no open incident exists for that service.
Include service name, load, capacity, and status in incident descriptions.
Be concise. Report facts, not commentary.
```

**Mayor:**
```
You are the Mayor. You set strategic priorities for the city.

Responsibilities:
1. read_city_state to understand current conditions
2. set_priority based on which failures are most critical
3. assign_task when work needs to be routed

Focus on the big picture: which services matter most, where to allocate effort.
The orchestrator handles routine dispatch — you handle strategic decisions.
```

### Changes

- `definitions.py` — updated system prompts for all 4 agents

---

## Section 4: Implementation Boundaries

### Changes Per File

| File | Changes |
|------|---------|
| `runner.py` | Rewrite `run_cycle()` with 3-phase orchestration; add `_triage()`, `_plan()`, `_dispatch()`; planner prompt; cycle tracking; agent attribution via `city_tools.set_current_agent()`; new `ChatOllama` import; accept `city_tools`, `kv`, `fs` constructor params |
| `audit.py` | Add `agent_name` param to `track()`; capture `lastrowid` on tracker |
| `tools.py` | Add `set_current_agent()`, `pop_audit_ids()`, `_recent_audit_ids` list; include `agent` field in `_emit()` events; pass `_current_agent` to `_audit_ctx` |
| `definitions.py` | Updated system prompts with explicit workflow checklists |
| `swarm.py` | `build_swarm()` returns `(compiled_swarm, city_tools)` tuple instead of just the swarm |
| `main.py` | Unpack `build_swarm()` tuple; pass `city_tools`, `kv`, `fs` to `AgentRunner` |

### What Does NOT Change

- `engine.py` — simulation logic unchanged
- `evaluator.py` — reads from production FS (correct behavior; the fix is making agents call `hotfix_prod`)
- `overlay.py` — staging/merge logic unchanged
- Dashboard code — already handles agent attribution from WebSocket messages
- `events.py` — no changes

### Testing

- Unit test: `_triage()` returns correct actions for various KV states (ok, degraded, failed combinations)
- Unit test: planner prompt parsing handles valid and malformed JSON
- Unit test: `set_current_agent` flows agent_name through to audit DB rows
- Unit test: `set_current_agent` flows through to event buffer entries
- Integration: run app, observe agents completing full deploy pipeline

### Future Work

- **Architect agent** — focused on proactive code quality and capacity improvements (not firefighting). Writes better `handle_load` implementations, optimizes config.json capacities, improves service resilience. Dispatched by planner when all services are healthy.
- Planner learning from past cycle outcomes
