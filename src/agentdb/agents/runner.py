"""Agent runner -- executes one LLM decision cycle and broadcasts results."""

from __future__ import annotations

import json
import time
import traceback

from langchain_core.messages import AIMessage, HumanMessage

from agentdb.dashboard.broadcast import Broadcaster
from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.simulation.engine import SimulationEngine


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

    async def run_cycle(self) -> None:
        """Run one agent decision cycle. Broadcasts status before/during/after."""
        for name in self._agent_names:
            await self._broadcaster.broadcast("agent_update", {
                "agent": name, "status": "working",
                "message": f"Checking city health (tick {self._engine.tick})...",
                "tick": self._engine.tick,
            })

        if self._swarm is None:
            await self._broadcast_idle_all()
            return

        try:
            result = await self._invoke_swarm()
            self._cycle_counter += 1
            participated = await self._process_messages(result)
            await self._flush_event_buffer()
            await self._broadcast_agent_statuses(participated)
            print(f"[tick {self._engine.tick}] Agents: {', '.join(participated.keys()) or 'none'}")
        except Exception as exc:
            print(f"[tick {self._engine.tick}] Agent error: {exc}")
            traceback.print_exc()
            self._event_buffer.clear()
            for name in self._agent_names:
                await self._broadcaster.broadcast("agent_update", {
                    "agent": name, "status": "error",
                    "message": str(exc)[:200], "tick": self._engine.tick,
                })

    async def _invoke_swarm(self) -> dict:
        prompt = (
            f"Tick {self._engine.tick}. Check city health. "
            "If any service is degraded or failed, create an incident "
            "and hand off to the appropriate agent. Otherwise report status."
        )
        return await self._swarm.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"configurable": {"thread_id": self._thread_id}},
        )

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
