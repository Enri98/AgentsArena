"""Core package for shared simulation-layer abstractions."""

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

__all__ = [
    "ArenaCoreError",
    "ConfigError",
    "InvalidGameConfig",
    "RulesError",
    "WrongPlayer",
    "IllegalAction",
    "GameFinished",
    "SerializationError",
    "RehydrationError",
    "UnknownGame",
    "DuplicateGameRegistration",
]
