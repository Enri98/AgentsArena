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
# Re-exported from the codec, which owns it. A second literal here drifted: it
# still said 1 after Phase 37 moved the wire to 2.
from arena.adapters.websocket.codec import (  # noqa: E402
    WIRE_SCHEMA_VERSION as WIRE_SCHEMA_VERSION,
)

# Every match is bounded. A game can loop forever (two Pig seats that only ever
# roll never bank a point), and one client holding both seat URLs could pin
# server memory that way. Exceeding it aborts with ``turn_limit_exceeded``.
MAX_TURNS_PER_MATCH: int = 5000

# Heartbeat defaults (Phase 32).  arena.server owns all deadline/heartbeat logic.
HEARTBEAT_INTERVAL_MS: int = 20_000
HEARTBEAT_MAX_MISSES: int = 2

# Match eviction (Phase 36 Slice 0).
# MatchRegistry held every Match forever, along with the per-match dicts hanging
# off app.state.  Spectators make that leak worse by holding sockets against
# dead matches, so eviction had to land before the spectator endpoint opened.
MATCH_RETENTION_S: float = 3600.0  # terminal matches, kept for late transcript reads
MATCH_MAX_AGE_S: float = 86_400.0  # non-terminal matches, presumed abandoned
MAX_TRACKED_MATCHES: int = 1000  # hard ceiling; oldest terminal matches shed first
