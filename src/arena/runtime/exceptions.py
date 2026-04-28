"""Runtime-layer exceptions for pure local orchestration models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ArenaRuntimeError(Exception):
    """Base class for pure runtime-layer errors."""

    default_code = "arena_runtime_error"

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


class InvalidMatchId(ArenaRuntimeError):
    """Raised when a runtime match id is invalid."""

    default_code = "invalid_match_id"


class InvalidPlayerRecord(ArenaRuntimeError):
    """Raised when runtime player metadata is invalid."""

    default_code = "invalid_player_record"


class RuntimeStateError(ArenaRuntimeError):
    """Raised when a runtime operation conflicts with lifecycle state."""

    default_code = "runtime_state_error"


class RuntimeAbortedError(ArenaRuntimeError):
    """Raised when a runtime session aborts instead of finishing normally."""

    default_code = "runtime_aborted"


__all__ = [
    "ArenaRuntimeError",
    "InvalidMatchId",
    "InvalidPlayerRecord",
    "RuntimeAbortedError",
    "RuntimeStateError",
]
