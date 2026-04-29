"""FastAPI application factory for arena.server.

Structured JSON logging will be added in Phase 33.
"""

from __future__ import annotations

from fastapi import FastAPI

from arena.server.registry import MatchRegistry
from arena.server.routes_http import router as http_router
from arena.server.routes_ws import router as ws_router


def create_app(game_registry=None) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    game_registry:
        A ``GameRegistry`` instance. Defaults to ``build_default_registry()``
        so both connect4 and tictactoe are available out of the box.
    """

    if game_registry is None:
        from arena.games import build_default_registry

        game_registry = build_default_registry()

    app = FastAPI(title="AgentsArena", version="0.1.0")
    app.state.match_registry = MatchRegistry(game_registry)

    app.include_router(http_router)
    app.include_router(ws_router)

    return app
