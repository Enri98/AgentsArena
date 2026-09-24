"""Rock-Paper-Scissors: the Phase 41 exemplar simultaneous-move game."""

from arena.games.rps.actions import SHAPES, RpsAction, Throw
from arena.games.rps.config import RpsConfig
from arena.games.rps.definition import (
    RPS_GAME_ID,
    RpsGameDefinition,
    build_rps_game_definition,
    register_rps,
)
from arena.games.rps.events import RoundPlayed, RpsMatchDecided
from arena.games.rps.observation import RpsObservation
from arena.games.rps.rules import RpsRulesEngine
from arena.games.rps.serializer import RpsSerializer
from arena.games.rps.state import RoundResult, RpsState

__all__ = [
    "RPS_GAME_ID",
    "RoundPlayed",
    "RoundResult",
    "RpsAction",
    "RpsConfig",
    "RpsGameDefinition",
    "RpsMatchDecided",
    "RpsObservation",
    "RpsRulesEngine",
    "RpsSerializer",
    "RpsState",
    "SHAPES",
    "Throw",
    "build_rps_game_definition",
    "register_rps",
]
