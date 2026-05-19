"""Server-side defaults and bounds from protocol §4.1."""

from __future__ import annotations

DEFAULT_PER_TURN_DEADLINE_MS: int = 30000
DEFAULT_PER_ACTION_RETRY_BUDGET: int = 3
DEFAULT_DISCONNECT_GRACE_MS: int = 30000

MAX_PER_TURN_DEADLINE_MS: int = 600000
RETRY_BUDGET_MIN: int = 0
RETRY_BUDGET_MAX: int = 10
MAX_DISCONNECT_GRACE_MS: int = 600000

GAME_SCHEMA_VERSION: int = 1
WIRE_SCHEMA_VERSION: int = 1

# Heartbeat defaults (Phase 32).  arena.server owns all deadline/heartbeat logic.
HEARTBEAT_INTERVAL_MS: int = 20_000
HEARTBEAT_MAX_MISSES: int = 2
