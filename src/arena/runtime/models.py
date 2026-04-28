"""Pure runtime-layer value objects and orchestration event records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arena.core.types import Seat
from arena.runtime.exceptions import InvalidPlayerRecord
from arena.runtime.ids import MatchId


@dataclass(frozen=True)
class PlayerRecord:
    """Runtime-owned player metadata paired with an assigned seat."""

    player_id: str
    seat: Seat
    label: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.player_id, str):
            raise InvalidPlayerRecord("player_id must be a string")
        if not self.player_id.strip():
            raise InvalidPlayerRecord("player_id must not be empty")

        if isinstance(self.seat, bool) or not isinstance(self.seat, int):
            raise InvalidPlayerRecord("seat must be an integer")

        if self.label is not None and not isinstance(self.label, str):
            raise InvalidPlayerRecord("label must be a string when provided")

        if self.label is not None and not self.label.strip():
            raise InvalidPlayerRecord("label must not be empty when provided")


class RuntimeLifecycle(StrEnum):
    """Runtime lifecycle states for a local session."""

    CREATED = "created"
    RUNNING = "running"
    FINISHED = "finished"
    ABORTED = "aborted"


class AbortReason(StrEnum):
    """Stable runtime abort reason codes."""

    ADAPTER_ERROR = "adapter_error"
    CORE_ERROR = "core_error"
    DEPENDENCY_ERROR = "dependency_error"
    INVALID_STATE = "invalid_state"
    MISSING_POLICY = "missing_policy"
    RUNTIME_ERROR = "runtime_error"
    CANCELLED = "cancelled"
    USER_QUIT = "user_quit"
    USER_INTERRUPT = "user_interrupt"


@dataclass(frozen=True)
class AbortMetadata:
    """Structured runtime abort details, with optional cause metadata."""

    reason: AbortReason
    message: str
    cause_type: str | None = None
    cause_message: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.message, str):
            raise ValueError("abort message must be a string")
        if not self.message.strip():
            raise ValueError("abort message must not be empty")

        if self.cause_type is not None and not isinstance(self.cause_type, str):
            raise ValueError("cause_type must be a string when provided")

        if self.cause_type is not None and not self.cause_type.strip():
            raise ValueError("cause_type must not be empty when provided")

        if self.cause_message is not None and not isinstance(self.cause_message, str):
            raise ValueError("cause_message must be a string when provided")

        if self.cause_message is not None and not self.cause_message.strip():
            raise ValueError("cause_message must not be empty when provided")

    @classmethod
    def from_cause(
        cls,
        *,
        reason: AbortReason,
        message: str,
        cause: BaseException | None,
    ) -> AbortMetadata:
        """Build abort metadata from an exception while preserving its shape."""

        if cause is None:
            return cls(reason=reason, message=message)

        cause_message = str(cause).strip() or None
        return cls(
            reason=reason,
            message=message,
            cause_type=cause.__class__.__name__,
            cause_message=cause_message,
        )


@dataclass(frozen=True)
class RuntimeEvent:
    """Base class for runtime-layer orchestration facts."""

    match_id: MatchId

    @property
    def event_type(self) -> str:
        """Return a stable event type identifier for the concrete event."""

        return self.__class__.__name__


@dataclass(frozen=True)
class MatchCreated(RuntimeEvent):
    """A runtime session was created with an assigned player/seat roster."""

    players: tuple[PlayerRecord, ...]


@dataclass(frozen=True)
class MatchStarted(RuntimeEvent):
    """A runtime session moved from created to running."""


@dataclass(frozen=True)
class TurnRequested(RuntimeEvent):
    """A runtime session requested an action from the active seat's policy."""

    seat: Seat


@dataclass(frozen=True)
class TurnAccepted(RuntimeEvent):
    """A runtime session accepted and applied one policy action."""

    seat: Seat
    turn_index: int


@dataclass(frozen=True)
class MatchFinished(RuntimeEvent):
    """A runtime session reached a finished lifecycle state."""


@dataclass(frozen=True)
class MatchAborted(RuntimeEvent):
    """A runtime session aborted before normal completion."""

    abort: AbortMetadata


@dataclass(frozen=True)
class PolicyRetried(RuntimeEvent):
    """A policy produced an illegal action and the agent will retry."""

    seat: Seat
    attempt: int
    reason_summary: str


@dataclass(frozen=True)
class PolicyDecided(RuntimeEvent):
    """A policy committed to a legal action; carries any model reasoning text."""

    seat: Seat
    attempt: int
    thought: str


__all__ = [
    "AbortMetadata",
    "AbortReason",
    "MatchAborted",
    "MatchCreated",
    "MatchFinished",
    "MatchStarted",
    "PlayerRecord",
    "PolicyDecided",
    "PolicyRetried",
    "RuntimeEvent",
    "RuntimeLifecycle",
    "TurnAccepted",
    "TurnRequested",
]
