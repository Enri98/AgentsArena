"""arena.server — FastAPI server for hosting AgentsArena matches."""

from __future__ import annotations

from arena.server.app import create_app
from arena.server.config import GAME_SCHEMA_VERSION, WIRE_SCHEMA_VERSION
from arena.server.registry import Match, MatchRegistry

__all__ = [
    "GAME_SCHEMA_VERSION",
    "WIRE_SCHEMA_VERSION",
    "Match",
    "MatchRegistry",
    "create_app",
]
