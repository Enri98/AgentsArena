"""Nim domain models and rules implementation."""

from arena.games.nim.actions import TakeObjects
from arena.games.nim.config import NimConfig
from arena.games.nim.definition import (
    NIM_GAME_ID,
    NimGameDefinition,
    build_nim_game_definition,
    register_nim,
)
from arena.games.nim.events import NimMatchWon, NimObjectsTaken
from arena.games.nim.observation import NimObservation
from arena.games.nim.rules import NimRulesEngine
from arena.games.nim.serializer import NimSerializer
from arena.games.nim.state import NimState

__all__ = [
    "NIM_GAME_ID",
    "NimConfig",
    "NimGameDefinition",
    "NimMatchWon",
    "NimObservation",
    "NimObjectsTaken",
    "NimRulesEngine",
    "NimSerializer",
    "NimState",
    "TakeObjects",
    "build_nim_game_definition",
    "register_nim",
]
