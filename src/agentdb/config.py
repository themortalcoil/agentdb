"""Runtime configuration from environment.

Used by the main entry point and any code that needs DB path or tick interval.
"""

import os

# Database path for SQLite (AgentFS + tool_calls audit).
DB_PATH: str = os.environ.get("AGENTDB_DB", "city.db")

# Seconds between simulation ticks.
TICK_INTERVAL: float = float(os.environ.get("TICK_INTERVAL", "5"))

# Dashboard host/port (for reference; uvicorn is configured in main).
HOST: str = os.environ.get("AGENTDB_HOST", "0.0.0.0")
PORT: int = int(os.environ.get("AGENTDB_PORT", "8000"))
