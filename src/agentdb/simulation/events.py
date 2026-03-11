"""City event types and generation."""

import math
import random
from dataclasses import dataclass
from enum import Enum


class EventType(Enum):
    DEMAND_SPIKE = "demand_spike"
    SERVICE_FAILURE = "service_failure"
    INFRASTRUCTURE_DECAY = "infrastructure_decay"
    CITIZEN_COMPLAINT = "citizen_complaint"
    CASCADE_FAILURE = "cascade_failure"
    BUDGET_SHORTFALL = "budget_shortfall"


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def weight(self) -> int:
        return {"low": 1, "medium": 2, "high": 3, "critical": 4}[self.value]


EVENT_PROBABILITIES: dict[EventType, float] = {
    EventType.INFRASTRUCTURE_DECAY: 0.05,
    EventType.CITIZEN_COMPLAINT: 0.03,
    EventType.BUDGET_SHORTFALL: 0.02,
}


@dataclass
class CityEvent:
    event_type: EventType
    service: str
    severity: Severity
    message: str
    tick: int

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "service": self.service,
            "severity": self.severity.value,
            "message": self.message,
            "tick": self.tick,
        }


def generate_demand(tick: int, seed_offset: int = 0) -> float:
    """Generate citizen demand using sine wave + noise for daily patterns."""
    base = 0.6 + 0.4 * math.sin(2 * math.pi * (tick + seed_offset) / 100)
    noise = math.sin(tick * 7.3 + seed_offset * 3.1) * 0.15
    return max(0.0, base + noise)


def roll_random_events(
    services: list[str],
    tick: int,
    rng: random.Random,
) -> list[CityEvent]:
    """Roll for random events across all services."""
    events: list[CityEvent] = []
    for service in services:
        for event_type, prob in EVENT_PROBABILITIES.items():
            if rng.random() < prob:
                severity = {
                    EventType.INFRASTRUCTURE_DECAY: Severity.LOW,
                    EventType.CITIZEN_COMPLAINT: Severity.LOW,
                    EventType.BUDGET_SHORTFALL: Severity.MEDIUM,
                }[event_type]
                events.append(
                    CityEvent(
                        event_type=event_type,
                        service=service,
                        severity=severity,
                        message=f"{event_type.value} on {service}",
                        tick=tick,
                    )
                )
    return events
