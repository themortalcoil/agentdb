"""City simulation engine -- the heartbeat of the city."""

import random
import sqlite3
from collections.abc import Callable

from agentdb.db.filesystem import VirtualFS
from agentdb.db.kvstore import KVStore
from agentdb.simulation.deps import ServiceGraph
from agentdb.simulation.evaluator import ServiceEvaluator
from agentdb.simulation.events import (
    CityEvent,
    EventType,
    Severity,
    generate_demand,
    roll_random_events,
)


class SimulationEngine:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fs: VirtualFS,
        kv: KVStore,
        seed: int = 0,
        graph: ServiceGraph | None = None,
    ):
        self._conn = conn
        self._fs = fs
        self._kv = kv
        self._rng = random.Random(seed)
        self._graph = graph or ServiceGraph.default_city()
        self._evaluator = ServiceEvaluator(fs)
        self._listeners: list[Callable[[CityEvent], None]] = []
        self.tick = 0
        self.paused = False

    def on_event(self, callback: Callable[[CityEvent], None]) -> None:
        self._listeners.append(callback)

    def _emit(self, event: CityEvent) -> None:
        for listener in self._listeners:
            listener(event)

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def get_full_state(self) -> dict:
        """Return full simulation state for the dashboard API."""
        items = self._kv.list_prefix("")
        return {"state": dict(items), "tick": self.tick, "paused": self.paused}

    async def step(self) -> list[CityEvent]:
        """Run one simulation tick. Returns events generated."""
        if self.paused:
            return []

        self.tick += 1
        all_events: list[CityEvent] = []

        # 1. Update demand per service
        for i, service in enumerate(self._graph.services):
            load = generate_demand(self.tick, seed_offset=i * 17)
            self._kv.set(f"service:{service}:load", f"{load:.3f}")

        # 2. Evaluate each service's code
        failed_services: list[str] = []
        for service in self._graph.services:
            load_raw = self._kv.get(f"service:{service}:load", "0.5")
            load = float(load_raw or "0.5")
            result = self._evaluator.evaluate(service, load)
            old_status = self._kv.get(f"service:{service}:status", "ok")
            self._kv.set(f"service:{service}:status", result.status)
            self._kv.set(f"service:{service}:capacity", f"{result.capacity:.3f}")

            if result.status == "failed" and old_status != "failed":
                event = CityEvent(
                    event_type=EventType.SERVICE_FAILURE,
                    service=service,
                    severity=Severity.HIGH,
                    message=f"{service} failed: {result.error}",
                    tick=self.tick,
                )
                all_events.append(event)
                failed_services.append(service)
            elif (
                result.status == "degraded" and old_status != "degraded" and load > result.capacity
            ):
                event = CityEvent(
                    event_type=EventType.DEMAND_SPIKE,
                    service=service,
                    severity=Severity.MEDIUM,
                    message=f"{service} load ({load:.2f}) exceeds capacity",
                    tick=self.tick,
                )
                all_events.append(event)

        # 3. Check for cascade failures
        for failed in failed_services:
            cascade = self._graph.get_cascade_order(failed)
            for affected in cascade:
                current = self._kv.get(f"service:{affected}:status", "ok")
                if current != "failed":
                    self._kv.set(f"service:{affected}:status", "degraded")
                    event = CityEvent(
                        event_type=EventType.CASCADE_FAILURE,
                        service=affected,
                        severity=Severity.CRITICAL,
                        message=f"{affected} affected by {failed} failure",
                        tick=self.tick,
                        source=failed,
                    )
                    all_events.append(event)

        # 4. Roll random events
        random_events = roll_random_events(self._graph.services, self.tick, self._rng)
        all_events.extend(random_events)

        # 5. Update active incident count
        failure_count = sum(
            1 for s in self._graph.services if self._kv.get(f"service:{s}:status") == "failed"
        )
        self._kv.set("incident:active_count", str(failure_count))

        # 6. Emit all events
        for event in all_events:
            self._emit(event)

        return all_events
