"""FastAPI application factory for arena.server.

Structured JSON logging will be added in Phase 33.
"""

from __future__ import annotations

from fastapi import FastAPI

from arena.server.config import HEARTBEAT_INTERVAL_MS, HEARTBEAT_MAX_MISSES
from arena.server.registry import MatchRegistry
from arena.server.routes_http import router as http_router
from arena.server.routes_ws import router as ws_router


def create_app(
    game_registry=None,
    *,
    heartbeat_interval_ms: int | None = None,
    heartbeat_max_misses: int | None = None,
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
    """

    if game_registry is None:
        from arena.games import build_default_registry

        game_registry = build_default_registry()

    app = FastAPI(title="AgentsArena", version="0.1.0")
    app.state.match_registry = MatchRegistry(game_registry)
    app.state.heartbeat_interval_ms = (
        heartbeat_interval_ms if heartbeat_interval_ms is not None else HEARTBEAT_INTERVAL_MS
    )
    app.state.heartbeat_max_misses = (
        heartbeat_max_misses if heartbeat_max_misses is not None else HEARTBEAT_MAX_MISSES
    )

    app.include_router(http_router)
    app.include_router(ws_router)

    return app
