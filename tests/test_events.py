import random
from agentdb.simulation.events import (
    CityEvent,
    EventType,
    Severity,
    generate_demand,
    roll_random_events,
)


def test_event_type_values():
    assert EventType.DEMAND_SPIKE.value == "demand_spike"
    assert EventType.CASCADE_FAILURE.value == "cascade_failure"


def test_severity_ordering():
    assert Severity.LOW.weight < Severity.MEDIUM.weight
    assert Severity.MEDIUM.weight < Severity.HIGH.weight
    assert Severity.HIGH.weight < Severity.CRITICAL.weight


def test_generate_demand_produces_values():
    """Demand curve should produce values between 0 and ~2.0."""
    demands = [generate_demand(tick=t, seed_offset=0) for t in range(100)]
    assert all(0 <= d <= 2.0 for d in demands)
    assert len(set(round(d, 2) for d in demands)) > 1


def test_roll_random_events_deterministic():
    rng = random.Random(42)
    events1 = roll_random_events(services=["power-grid", "water-system"], tick=10, rng=rng)
    rng2 = random.Random(42)
    events2 = roll_random_events(services=["power-grid", "water-system"], tick=10, rng=rng2)
    assert len(events1) == len(events2)
    for e1, e2 in zip(events1, events2):
        assert e1.event_type == e2.event_type
        assert e1.service == e2.service


def test_city_event_to_dict():
    event = CityEvent(
        event_type=EventType.SERVICE_FAILURE,
        service="power-grid",
        severity=Severity.HIGH,
        message="Power grid crashed",
        tick=5,
    )
    d = event.to_dict()
    assert d["event_type"] == "service_failure"
    assert d["service"] == "power-grid"
    assert d["severity"] == "high"
