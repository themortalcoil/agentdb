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

### Fix: Retroactive Attribution

After `_invoke_swarm()` returns, `_process_messages` already iterates messages grouped by agent. For each agent's tool calls, we update the corresponding audit log rows with the agent name.

**`audit.py` changes:**
- Add `agent_name` parameter to `track()` context manager (default `None` for backward compatibility)
- Add `update_agent_name(ids: list[int], agent_name: str)` method for batch retroactive updates

**`tools.py` changes:**
- `_audit_ctx` returns the inserted row ID via the tracker
- `_emit()` includes an `agent` field (value of `_current_agent`)
- Add `set_current_agent(name: str | None)` method — called by the runner before each agent dispatch

**`runner.py` changes:**
- Before dispatching each agent task, call `city_tools.set_current_agent(agent_name)` so event buffer entries include attribution
- After swarm returns, match tool calls to audit rows and update attribution retroactively

**Why retroactive + set_current_agent (both)?**
- `set_current_agent` handles the event buffer (real-time WebSocket broadcasts)
- Retroactive update handles audit log rows (since LangGraph's internal tool execution doesn't pass through our code)

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
- Open incidents (scan `/city/incidents/` files)
- What agents attempted last cycle and whether it worked

If everything is ok — no failed or degraded services, no open incidents — broadcast idle status for all agents. No LLM calls. This is the "lightweight check" that runs every cycle.

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

Run tasks sequentially through the existing swarm (one `ainvoke` per task with targeted prompt). The swarm's handoff mechanism still works — if fixer needs to hand off to monitor, it can.

### Cycle Tracking

The runner keeps `_last_plan` (the plan) and `_last_results` (what happened) so the planner can see what was attempted last cycle and adjust. If a service is still failed after a fix attempt, the planner can try a different approach.

### Changes

- `runner.py` — rewrite `run_cycle()` with three phases; add `_triage()`, `_plan()`, `_dispatch()` methods; add planner prompt template; add `_last_plan` / `_last_results` tracking

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
| `runner.py` | Rewrite `run_cycle()` with 3-phase orchestration; add `_triage()`, `_plan()`, `_dispatch()`; planner prompt; cycle tracking; agent attribution wiring |
| `audit.py` | Add `agent_name` param to `track()`; add `update_agent_name()` for retroactive attribution |
| `tools.py` | Add `set_current_agent()`, include `agent` field in `_emit()` events, return audit row IDs from `_audit_ctx` |
| `definitions.py` | Updated system prompts with explicit workflow checklists |

### What Does NOT Change

- `swarm.py` — swarm topology and tool wiring unchanged
- `engine.py` — simulation logic unchanged
- `evaluator.py` — reads from production FS (correct behavior; the fix is making agents call `hotfix_prod`)
- `overlay.py` — staging/merge logic unchanged
- Dashboard code — already handles agent attribution from WebSocket messages
- `events.py` — no changes

### Testing

- Unit test: `_triage()` returns correct actions for various KV states (ok, degraded, failed combinations)
- Unit test: planner prompt parsing handles valid and malformed JSON
- Unit test: retroactive audit attribution updates rows correctly
- Unit test: `set_current_agent` flows through to event buffer entries
- Integration: run app, observe agents completing full deploy pipeline

### Future Work

- **Architect agent** — focused on proactive code quality and capacity improvements (not firefighting). Writes better `handle_load` implementations, optimizes config.json capacities, improves service resilience. Dispatched by planner when all services are healthy.
- Planner learning from past cycle outcomes
