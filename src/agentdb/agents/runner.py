"""Agent runner -- executes one LLM decision cycle and broadcasts results."""

from __future__ import annotations

import json
import re
import time
import traceback

from langchain_core.messages import AIMessage, HumanMessage

from agentdb.dashboard.broadcast import Broadcaster
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.simulation.engine import SimulationEngine


PLANNER_PROMPT = """\
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

Respond with JSON only: {{"tasks": [{{"agent": "...", "instruction": "..."}}]}}"""


class AgentRunner:
    def __init__(
        self,
        swarm,
        broadcaster: Broadcaster,
        engine: SimulationEngine,
        event_buffer: list,
        agent_names: list[str],
        kv: KVStore | None = None,
        fs: VirtualFS | None = None,
        city_tools=None,
        thread_id: str = "city-sim",
    ):
        self._swarm = swarm
        self._broadcaster = broadcaster
        self._engine = engine
        self._event_buffer = event_buffer
        self._agent_names = agent_names
        self._kv = kv
        self._fs = fs
        self._city_tools = city_tools
        self._thread_id = thread_id
        self._cycle_counter = 0
        self._last_plan: dict | None = None
        self._last_results: dict | None = None

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

    def _triage(self) -> dict:
        """Deterministic triage: inspect KV state and FS for actionable work."""
        failed = []
        degraded = []
        services = {}

        if self._kv is not None:
            service_keys = self._kv.list_prefix("service:")
            service_names = sorted({k.split(":")[1] for k, _ in service_keys})
            for svc in service_names:
                status = self._kv.get(f"service:{svc}:status", "ok")
                load = self._kv.get(f"service:{svc}:load", "0.5")
                capacity = self._kv.get(f"service:{svc}:capacity", "1.0")
                services[svc] = {"status": status, "load": load, "capacity": capacity}
                if status == "failed":
                    failed.append(svc)
                elif status == "degraded":
                    degraded.append(svc)

        # Scan recent incidents (ignore stale ones > 60 seconds old)
        recent_incidents = []
        if self._fs is not None:
            incident_names = self._fs.list_dir("/city/incidents")
            for name in incident_names:
                content = self._fs.read_file(f"/city/incidents/{name}")
                if content is None:
                    continue
                try:
                    inc = json.loads(content)
                except json.JSONDecodeError:
                    continue
                created_at = inc.get("created_at", 0)
                age_seconds = time.time() - created_at
                if age_seconds <= 60:
                    recent_incidents.append(inc)

        needs_action = len(failed) > 0 or len(degraded) > 0 or len(recent_incidents) > 0

        return {
            "needs_action": needs_action,
            "failed": failed,
            "degraded": degraded,
            "services": services,
            "recent_incidents": recent_incidents,
            "tick": self._engine.tick,
        }

    @staticmethod
    def _parse_plan(raw: str) -> list[dict]:
        """Parse planner LLM output into a list of task dicts."""
        # Strip markdown code fences if present
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
        if match:
            raw = match.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, dict):
            return []
        tasks = data.get("tasks")
        if not isinstance(tasks, list):
            return []
        return tasks

    async def _plan(self, triage: dict) -> list[dict]:
        """Call LLM planner to generate targeted agent tasks."""
        try:
            from langchain_ollama import ChatOllama
            planner_llm = ChatOllama(model="glm-5:cloud")

            triage_summary = json.dumps(triage, indent=2)
            last_results = json.dumps(self._last_results or {}, indent=2)
            prompt = PLANNER_PROMPT.format(
                triage_summary=triage_summary,
                last_plan_results=last_results,
            )

            response = await planner_llm.ainvoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            tasks = self._parse_plan(content)
            if tasks:
                return tasks
        except Exception as exc:
            print(f"[tick {self._engine.tick}] Planner error: {exc}")

        # Fallback: return empty (caller will use generic prompt)
        return []

    async def run_cycle(self) -> None:
        """Run one orchestration cycle: triage → plan → dispatch."""
        if self._swarm is None:
            await self._broadcast_idle_all()
            return

        # Phase 1: Deterministic triage
        triage = self._triage()
        if not triage["needs_action"]:
            await self._broadcast_idle_all()
            return

        # Phase 2: LLM planner
        planned_tasks = await self._plan(triage)

        # Phase 3: Dispatch
        if planned_tasks:
            await self._dispatch_planned(planned_tasks)
        else:
            # Fallback: generic prompt (planner failed or returned empty)
            await self._dispatch_generic()

    async def _dispatch_planned(self, tasks: list[dict]) -> None:
        """Dispatch agents with targeted instructions from the planner."""
        self._cycle_counter += 1
        all_participated: dict[str, str] = {}

        for i, task in enumerate(tasks):
            agent_name = task.get("agent", "")
            instruction = task.get("instruction", "")
            if not agent_name or not instruction:
                continue

            if self._city_tools is not None:
                self._city_tools.set_current_agent(agent_name)

            await self._broadcaster.broadcast("agent_update", {
                "agent": agent_name, "status": "working",
                "message": instruction[:200],
                "tick": self._engine.tick,
            })

            try:
                thread_id = f"cycle-{self._cycle_counter}-{i}"
                prompt = f"Tick {self._engine.tick}. {instruction}"
                result = await self._swarm.ainvoke(
                    {"messages": [HumanMessage(content=prompt)]},
                    config={"configurable": {"thread_id": thread_id}},
                )
                participated = await self._process_messages(result)
                all_participated.update(participated)
            except Exception as exc:
                print(f"[tick {self._engine.tick}] Dispatch error ({agent_name}): {exc}")
                await self._broadcaster.broadcast("agent_update", {
                    "agent": agent_name, "status": "error",
                    "message": str(exc)[:200], "tick": self._engine.tick,
                })

        # Clear agent attribution and drain audit IDs
        if self._city_tools is not None:
            self._city_tools.pop_audit_ids()
            self._city_tools.set_current_agent(None)

        await self._flush_event_buffer()
        await self._broadcast_agent_statuses(all_participated)

        # Track results for next cycle's planner
        self._last_plan = {"tasks": tasks}
        self._last_results = {
            "participated": list(all_participated.keys()),
            "tick": self._engine.tick,
        }
        print(f"[tick {self._engine.tick}] Planned: {len(tasks)} tasks, "
              f"Agents: {', '.join(all_participated.keys()) or 'none'}")

    async def _dispatch_generic(self) -> None:
        """Fallback: dispatch all agents with the original generic prompt."""
        self._cycle_counter += 1
        for name in self._agent_names:
            await self._broadcaster.broadcast("agent_update", {
                "agent": name, "status": "working",
                "message": f"Checking city health (tick {self._engine.tick})...",
                "tick": self._engine.tick,
            })

        try:
            thread_id = f"cycle-{self._cycle_counter}-generic"
            prompt = (
                f"Tick {self._engine.tick}. Check city health. "
                "If any service is degraded or failed, create an incident "
                "and hand off to the appropriate agent. Otherwise report status."
            )
            result = await self._swarm.ainvoke(
                {"messages": [HumanMessage(content=prompt)]},
                config={"configurable": {"thread_id": thread_id}},
            )
            participated = await self._process_messages(result)
            await self._flush_event_buffer()
            await self._broadcast_agent_statuses(participated)
            print(f"[tick {self._engine.tick}] Generic dispatch. "
                  f"Agents: {', '.join(participated.keys()) or 'none'}")
        except Exception as exc:
            print(f"[tick {self._engine.tick}] Agent error: {exc}")
            traceback.print_exc()
            self._event_buffer.clear()
            for name in self._agent_names:
                await self._broadcaster.broadcast("agent_update", {
                    "agent": name, "status": "error",
                    "message": str(exc)[:200], "tick": self._engine.tick,
                })

    async def _process_messages(self, result: dict) -> dict[str, str]:
        """Parse LangChain messages and broadcast agent_message events."""
        participated: dict[str, str] = {}
        for msg in result["messages"]:
            agent_name = getattr(msg, "name", None)
            if not isinstance(msg, AIMessage):
                continue
            if not agent_name or agent_name not in self._agent_names:
                continue
            if not getattr(msg, "content", ""):
                continue

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
            participated[agent_name] = msg.content[:200]

        return participated

    async def _flush_event_buffer(self) -> None:
        """Broadcast buffered file/overlay events from CityTools."""
        for event in self._event_buffer:
            etype = event["type"]
            payload = {k: v for k, v in event.items() if k != "type"}
            payload["tick"] = self._engine.tick
            await self._broadcaster.broadcast(etype, payload)
        self._event_buffer.clear()

    async def _broadcast_agent_statuses(self, participated: dict[str, str]) -> None:
        """Send acted/idle status for each agent."""
        for name, summary in participated.items():
            await self._broadcaster.broadcast("agent_update", {
                "agent": name, "status": "acted",
                "message": summary, "tick": self._engine.tick,
            })
            await self._broadcaster.broadcast("city_event", {
                "event_type": "agent_action", "service": name,
                "severity": "low",
                "message": f"Agent {name}: {summary[:120]}",
                "tick": self._engine.tick,
            })
        for name in self._agent_names:
            if name not in participated:
                await self._broadcaster.broadcast("agent_update", {
                    "agent": name, "status": "idle",
                    "message": "", "tick": self._engine.tick,
                })

    async def _broadcast_idle_all(self) -> None:
        for name in self._agent_names:
            await self._broadcaster.broadcast("agent_update", {
                "agent": name, "status": "idle",
                "message": "", "tick": self._engine.tick,
            })
