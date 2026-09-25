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

# The only uvicorn WebSocket implementation the match handlers work on; see
# arena.server.__main__. Tests and every deployment entry point must use it.
UVICORN_WS_IMPL: str = "websockets-sansio"

#: Protocol-level keepalive for every WebSocket, spectators included. The
#: application heartbeat pings only the active seat; a spectator (or an idle
#: seat) that stops reading is found by this one, and dropped. uvicorn's defaults
#: happen to match, but the bound on how long a dead reader can hold a socket and
#: its send buffer is a server property, so it is pinned here.
UVICORN_WS_PING_INTERVAL_S: float = 20.0
UVICORN_WS_PING_TIMEOUT_S: float = 20.0
#: Largest inbound frame. Clients send hellos, actions, and pongs: all small.
UVICORN_WS_MAX_SIZE: int = 1 << 20
#: permessage-deflate off. With it on, Node's built-in WebSocket client (undici,
#: which the TypeScript SDK uses) failed mid-match with 1006 after a few frames,
#: while the server believed everything was sent. Frames are bounded (a long
#: match's transcript is a few MB), so compression is not worth a client that
#: cannot talk to us. Tests serve the same way.
UVICORN_WS_PER_MESSAGE_DEFLATE: bool = False

#: Seconds a new WebSocket has to send its hello. Without a bound, a socket that
#: never spoke held its connection slots for as long as it stayed open.
HELLO_TIMEOUT_S: float = 10.0

# Heartbeat defaults (Phase 32).  arena.server owns all deadline/heartbeat logic.
HEARTBEAT_INTERVAL_MS: int = 20_000
HEARTBEAT_MAX_MISSES: int = 2

# Match eviction (Phase 36 Slice 0).
# MatchRegistry held every Match forever, along with the per-match dicts hanging
# off app.state.  Spectators make that leak worse by holding sockets against
# dead matches, so eviction had to land before the spectator endpoint opened.
MATCH_RETENTION_S: float = 3600.0  # terminal matches, kept for late transcript reads
MATCH_MAX_AGE_S: float = 86_400.0  # running matches, presumed abandoned
#: Created but never started (no seat pair ever joined). Cheap to create, so
#: they must not be able to sit in the registry for a day.
MATCH_UNSTARTED_MAX_AGE_S: float = 3600.0
#: Hard ceiling. When full, terminal matches are shed first, then never-started
#: ones, oldest first; a running match is never shed. If nothing can be shed,
#: POST /matches answers 503 server_busy.
MAX_TRACKED_MATCHES: int = 1000
