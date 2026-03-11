"""Service code evaluator -- imports and runs agent-written service code."""

import json
import types
from dataclasses import dataclass

from agentdb.db.filesystem import VirtualFS


@dataclass
class ServiceResult:
    status: str  # "ok", "degraded", "failed"
    capacity: float
    metrics: dict
    error: str | None = None

    @classmethod
    def failed(cls, error: str) -> "ServiceResult":
        return cls(status="failed", capacity=0.0, metrics={}, error=error)


class ServiceEvaluator:
    def __init__(self, fs: VirtualFS):
        self._fs = fs

    def evaluate(self, service_name: str, load: float) -> ServiceResult:
        code = self._fs.read_file(f"/city/services/{service_name}/main.py")
        if code is None:
            return ServiceResult.failed(
                f"Service '{service_name}' not found: no main.py"
            )

        config_raw = self._fs.read_file(
            f"/city/services/{service_name}/config.json"
        )
        try:
            config = json.loads(config_raw) if config_raw else {}
        except json.JSONDecodeError as e:
            return ServiceResult.failed(f"Invalid config.json: {e}")

        try:
            module = types.ModuleType(f"service_{service_name}")
            compiled = compile(code, f"{service_name}/main.py", "exec")
            exec(compiled, module.__dict__)  # noqa: S102
        except SyntaxError as e:
            return ServiceResult.failed(f"SyntaxError in main.py: {e}")
        except Exception as e:
            return ServiceResult.failed(
                f"Failed to load main.py: {type(e).__name__}: {e}"
            )

        if not hasattr(module, "handle_load"):
            return ServiceResult.failed(
                "main.py missing handle_load() function"
            )

        try:
            raw = module.handle_load(load, config)
            return ServiceResult(
                status=raw.get("status", "failed"),
                capacity=raw.get("capacity", 0.0),
                metrics=raw.get("metrics", {}),
            )
        except Exception as e:
            return ServiceResult.failed(f"{type(e).__name__}: {e}")
