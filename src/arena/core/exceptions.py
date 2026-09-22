"""Core domain exceptions for the pure simulation package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ArenaCoreError(Exception):
    """Base class for simulation-domain errors."""

    default_code = "arena_core_error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        resolved_message = message or self.__class__.__name__
        super().__init__(resolved_message)
        self.message = resolved_message
        self.code = code or self.default_code
        self.details = dict(details) if details is not None else None


class ConfigError(ArenaCoreError):
    """Base class for configuration validation errors."""

    default_code = "config_error"


class InvalidGameConfig(ConfigError):
    """Raised when a game configuration is invalid."""

    default_code = "invalid_game_config"


class IncompleteChanceSupport(ConfigError):
    """Raised when a game declares chance nodes but cannot resolve one.

    A match would stall at the first chance node, so the inconsistency is
    rejected at registration rather than discovered mid-game.
    """

    default_code = "incomplete_chance_support"


class IncompletePublicView(ConfigError):
    """Raised when a game declares hidden information but does not redact it.

    Registering such a game would broadcast private state to every seat, so the
    inconsistency is rejected at registration rather than discovered on the wire.
    """

    default_code = "incomplete_public_view"


class RulesError(ArenaCoreError):
    """Base class for rules- and move-validation errors."""

    default_code = "rules_error"


class WrongPlayer(RulesError):
    """Raised when a seat acts out of turn."""

    default_code = "wrong_player"


class IllegalAction(RulesError):
    """Raised when an action is illegal in the current state."""

    default_code = "illegal_action"


class GameFinished(RulesError):
    """Raised when a move is attempted after the game has finished."""

    default_code = "game_finished"


class ChanceResolutionError(RulesError):
    """Raised when a rules engine fails to make progress out of a chance node."""

    default_code = "chance_resolution_error"


class SerializationError(ArenaCoreError):
    """Base class for serialization failures."""

    default_code = "serialization_error"


class RehydrationError(SerializationError):
    """Raised when serialized data cannot be rehydrated safely."""

    default_code = "rehydration_error"


class UnknownGame(ArenaCoreError):
    """Raised when a requested game identifier is unknown."""

    default_code = "unknown_game"


class DuplicateGameRegistration(ArenaCoreError):
    """Raised when a game identifier is registered more than once."""

    default_code = "duplicate_game_registration"


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
