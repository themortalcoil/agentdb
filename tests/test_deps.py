from agentdb.simulation.deps import ServiceGraph


def test_default_city_services():
    g = ServiceGraph.default_city()
    assert set(g.services) == {
        "power-grid", "water-system", "traffic-control", "comms-network"
    }


def test_dependents():
    """power-grid failing should affect water-system and comms-network."""
    g = ServiceGraph.default_city()
    dependents = g.get_dependents("power-grid")
    assert "water-system" in dependents
    assert "comms-network" in dependents


def test_cascade_order():
    """Cascade from power-grid should ripple through all dependents."""
    g = ServiceGraph.default_city()
    cascade = g.get_cascade_order("power-grid")
    assert len(cascade) >= 2


def test_no_dependents():
    """traffic-control has no dependents in the default city."""
    g = ServiceGraph.default_city()
    dependents = g.get_dependents("traffic-control")
    assert dependents == []


def test_dependencies_of():
    """traffic-control depends on comms-network."""
    g = ServiceGraph.default_city()
    deps = g.get_dependencies("traffic-control")
    assert "comms-network" in deps
