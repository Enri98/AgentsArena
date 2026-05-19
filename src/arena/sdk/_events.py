"""SdkEvent dataclasses — one per meaningful server-to-client envelope type."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arena.adapters.websocket.messages import (
    ErrorBody,
    MatchAbortedBody,
    MatchFinishedBody,
    MatchStateBody,
    ObservationRequestBody,
    TurnCommittedBody,
    WelcomeBody,
)


@dataclass(frozen=True)
class WelcomeEvent:
    body: WelcomeBody


@dataclass(frozen=True)
class ObservationEvent:
    body: ObservationRequestBody  # .observation_request is ObservationRequestPayload


@dataclass(frozen=True)
class TurnCommittedEvent:
    body: TurnCommittedBody


@dataclass(frozen=True)
class MatchStateEvent:
    body: MatchStateBody


@dataclass(frozen=True)
class MatchFinishedEvent:
    body: MatchFinishedBody


@dataclass(frozen=True)
class MatchAbortedEvent:
    body: MatchAbortedBody


@dataclass(frozen=True)
class ErrorEvent:
    body: ErrorBody


SdkEvent = (
    WelcomeEvent
    | ObservationEvent
    | TurnCommittedEvent
    | MatchStateEvent
    | MatchFinishedEvent
    | MatchAbortedEvent
    | ErrorEvent
)

__all__: Sequence[str] = [
    "ErrorEvent",
    "MatchAbortedEvent",
    "MatchFinishedEvent",
    "MatchStateEvent",
    "ObservationEvent",
    "SdkEvent",
    "TurnCommittedEvent",
    "WelcomeEvent",
]
