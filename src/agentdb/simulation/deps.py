"""Service dependency graph for the city."""

from dataclasses import dataclass, field


@dataclass
class ServiceGraph:
    """Directed graph of service dependencies.

    An edge from A -> B means A depends on B (B failing affects A).
    """

    services: list[str] = field(default_factory=list)
    edges: dict[str, list[str]] = field(default_factory=dict)
    capacities: dict[str, float] = field(default_factory=dict)

    @classmethod
    def default_city(cls) -> "ServiceGraph":
        services = [
            "power-grid", "water-system", "traffic-control", "comms-network"
        ]
        edges = {
            "power-grid": [],
            "water-system": ["power-grid"],
            "comms-network": ["power-grid"],
            "traffic-control": ["comms-network"],
        }
        capacities = {
            "power-grid": 1.0,
            "water-system": 0.8,
            "traffic-control": 0.6,
            "comms-network": 0.9,
        }
        return cls(services=services, edges=edges, capacities=capacities)

    def get_dependencies(self, service: str) -> list[str]:
        return list(self.edges.get(service, []))

    def get_dependents(self, service: str) -> list[str]:
        return [s for s, deps in self.edges.items() if service in deps]

    def get_cascade_order(self, failed_service: str) -> list[str]:
        affected: list[str] = []
        queue = [failed_service]
        visited = {failed_service}
        while queue:
            current = queue.pop(0)
            dependents = self.get_dependents(current)
            for dep in dependents:
                if dep not in visited:
                    visited.add(dep)
                    affected.append(dep)
                    queue.append(dep)
        return affected
