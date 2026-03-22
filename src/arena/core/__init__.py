"""Core package for shared simulation-layer abstractions."""

from arena.core.actions import Action
from arena.core.exceptions import (
    ArenaCoreError,
    ConfigError,
    DuplicateGameRegistration,
    GameFinished,
    IllegalAction,
    InvalidGameConfig,
    RehydrationError,
    RulesError,
    SerializationError,
    UnknownGame,
    WrongPlayer,
)
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.registry import GameRegistry
from arena.core.rules_engine import RulesEngine, TransitionResult

__all__ = [
    "Action",
    "ArenaCoreError",
    "ConfigError",
    "GameDefinition",
    "GameRegistry",
    "InvalidGameConfig",
    "RulesError",
    "WrongPlayer",
    "IllegalAction",
    "GameFinished",
    "SerializationError",
    "RehydrationError",
    "UnknownGame",
    "DuplicateGameRegistration",
    "Observation",
    "RulesEngine",
    "TransitionResult",
]
