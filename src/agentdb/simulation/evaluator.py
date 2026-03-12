"""Service code evaluator -- runs agent-written service code in a subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

from agentdb.db.filesystem import VirtualFS

EVAL_TIMEOUT = 5  # seconds

# Script run in the child process. Receives JSON on stdin, prints JSON on stdout.
# Uses a restricted builtins whitelist — no imports, no file I/O, no network.
_RUNNER_SCRIPT = r'''
import json, sys

data = json.loads(sys.stdin.read())

_SAFE_BUILTINS = {
    "len": len, "dict": dict, "list": list, "tuple": tuple, "set": set,
    "float": float, "int": int, "str": str, "bool": bool,
    "round": round, "range": range, "enumerate": enumerate,
    "min": min, "max": max, "abs": abs, "sum": sum, "sorted": sorted,
    "zip": zip, "map": map, "filter": filter,
    "True": True, "False": False, "None": None,
    "isinstance": isinstance, "type": type,
    "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
}

namespace = {"__builtins__": _SAFE_BUILTINS}
exec(compile(data["code"], "<service>", "exec"), namespace)

fn = namespace.get("handle_load")
if fn is None:
    print(json.dumps({"__error__": "main.py missing handle_load() function"}))
    sys.exit(0)

result = fn(data["load"], data["config"])
if not isinstance(result, dict):
    print(json.dumps({"__error__": "handle_load() must return dict, got " + type(result).__name__}))
    sys.exit(0)

print(json.dumps(result))
'''


@dataclass
class ServiceResult:
    status: str  # "ok", "degraded", "failed"
    capacity: float
    metrics: dict
    error: str | None = None

    @classmethod
    def failed(cls, error: str) -> ServiceResult:
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
            proc = subprocess.Popen(
                [sys.executable, "-c", _RUNNER_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate(
                input=json.dumps({"code": code, "load": load, "config": config}),
                timeout=EVAL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return ServiceResult.failed("Evaluation timeout")
        except OSError as e:
            return ServiceResult.failed(f"Subprocess error: {e}")

        if proc.returncode != 0:
            error_msg = stderr.strip() if stderr.strip() else f"Process exited with code {proc.returncode}"
            return ServiceResult.failed(error_msg)

        try:
            raw = json.loads(stdout)
        except json.JSONDecodeError:
            error_msg = stderr.strip() if stderr.strip() else "No valid JSON output"
            return ServiceResult.failed(error_msg)

        if "__error__" in raw:
            return ServiceResult.failed(raw["__error__"])

        return ServiceResult(
            status=raw.get("status", "failed"),
            capacity=raw.get("capacity", 0.0),
            metrics=raw.get("metrics", {}),
        )
