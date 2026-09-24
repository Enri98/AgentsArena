"""FastAPI application factory for arena.server.

Structured JSON logging will be added in Phase 33.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from arena.server.config import (
    HEARTBEAT_INTERVAL_MS,
    HEARTBEAT_MAX_MISSES,
    MAX_TURNS_PER_MATCH,
)
from arena.server.rate_limits import RateLimiter
from arena.server.registry import MatchRegistry
from arena.server.routes_http import router as http_router
from arena.server.routes_ws import router as ws_router
from arena.server.runtime_bridge import forget_match_transcripts
from arena.server.transcript_store import MemoryTranscriptStore, TranscriptStore


def _wake_waiters(app_state: object, match_id: str) -> None:
    """Close whoever still waits on an evicted match.

    Only a match that never started, or one already over, is evicted. A seat
    waiting for its opponent, or a spectator parked for a start that will now
    never come, would otherwise wait until the client gave up. Eviction runs
    inside POST /matches on the event loop, so the closes can be scheduled.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    done = getattr(app_state, "_ws_done_events", {}).get(match_id)
    if done is not None:
        done.set()  # parked spectators leave their read loop and close
    for conn in (getattr(app_state, "_ws_seat_slots", {}).get(match_id) or {}).values():
        if conn is not None:
            loop.create_task(_close_quietly(conn.websocket, 4410, "match_expired"))
    for spectator in getattr(app_state, "_ws_pending_spectators", {}).get(match_id, []):
        loop.create_task(_close_quietly(spectator.websocket, 4410, "match_expired"))


async def _close_quietly(ws: object, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)  # type: ignore[attr-defined]
    except Exception:
        pass


def create_app(
    game_registry=None,
    *,
    heartbeat_interval_ms: int | None = None,
    heartbeat_max_misses: int | None = None,
    rate_limiter: RateLimiter | None = None,
    max_turns_per_match: int | None = None,
    transcript_store: TranscriptStore | None = None,
    client_ip_header: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    game_registry:
        A ``GameRegistry`` instance. Defaults to ``build_default_registry()``
        so both connect4 and tictactoe are available out of the box.
    heartbeat_interval_ms:
        Override the default heartbeat ping interval (milliseconds).
        Defaults to ``HEARTBEAT_INTERVAL_MS`` from server config (20 000 ms).
    heartbeat_max_misses:
        Override the maximum consecutive missed pongs before the connection is
        closed with 4408.  Defaults to ``HEARTBEAT_MAX_MISSES`` from config (2).
    rate_limiter:
        Override the protocol §13 rate limiter.  Defaults to a ``RateLimiter``
        with the hardcoded v1 caps.  Tests inject one with small caps.
    transcript_store:
        Where ended matches' public transcripts are kept (Phase 40). Defaults to
        a bounded in-memory store; ``python -m arena.server`` can pass a file or
        SQLite store for durability. The app closes it on shutdown.
    client_ip_header:
        A request header carrying the client address, set by a trusted reverse
        proxy (``Fly-Client-IP``). Rate limits bucket by it instead of the TCP
        peer. Leave unset unless the proxy is the only way in.
    """

    if game_registry is None:
        from arena.games import build_default_registry

        game_registry = build_default_registry()

    store: TranscriptStore = (
        transcript_store if transcript_store is not None else MemoryTranscriptStore()
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            store.close()

    app = FastAPI(title="AgentsArena", version="0.1.0", lifespan=lifespan)
    app.state.transcript_store = store
    app.state.client_ip_header = client_ip_header or None

    limiter = rate_limiter if rate_limiter is not None else RateLimiter()

    #: Per-match bookkeeping is spread across lazily-created dicts on app.state
    #: (see arena.server.routes_ws) plus the rate limiter's per-match counters.
    #: Evicting a Match without clearing these leaks them for the process
    #: lifetime, which spectators would make materially worse.
    _PER_MATCH_STATE_ATTRS = (
        "_ws_seat_slots",
        "_ws_ready_events",
        "_ws_done_events",
        "_ws_reconnect_events",
        "_ws_reconnect_conns",
        "_ws_match_conns",
        "_ws_pending_spectators",
    )

    def _release_match_state(match_id: str) -> None:
        _wake_waiters(app.state, match_id)
        for attr in _PER_MATCH_STATE_ATTRS:
            container = getattr(app.state, attr, None)
            if isinstance(container, dict):
                container.pop(match_id, None)
        limiter.forget_match(match_id)
        forget_match_transcripts(match_id)

    app.state.match_registry = MatchRegistry(game_registry, on_evict=_release_match_state)
    app.state.heartbeat_interval_ms = (
        heartbeat_interval_ms if heartbeat_interval_ms is not None else HEARTBEAT_INTERVAL_MS
    )
    app.state.heartbeat_max_misses = (
        heartbeat_max_misses if heartbeat_max_misses is not None else HEARTBEAT_MAX_MISSES
    )
    app.state.rate_limiter = limiter
    # Committed turns per match, chance turns included; see config.
    app.state.max_turns_per_match = (
        max_turns_per_match if max_turns_per_match is not None else MAX_TURNS_PER_MATCH
    )

    app.include_router(http_router)
    app.include_router(ws_router)

    return app
