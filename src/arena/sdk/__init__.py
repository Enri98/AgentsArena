"""arena.sdk — reference Python client for arena.server.

Public API::

    from arena.sdk import Session, LocalSession, connect
    from arena.sdk import (
        SdkError, ProtocolError, SchemaVersionError, MatchNotFoundError,
        SeatTakenError, MatchAbortedError, ActionRejectedError, HandshakeError,
    )
    from arena.sdk import (
        ObservationEvent, TurnCommittedEvent, MatchFinishedEvent,
        MatchAbortedEvent, MatchStateEvent, WelcomeEvent, ErrorEvent, SdkEvent,
    )
"""
from arena.sdk._connect import _run_session, connect
from arena.sdk._events import (
    ErrorEvent,
    MatchAbortedEvent,
    MatchFinishedEvent,
    MatchStateEvent,
    ObservationEvent,
    SdkEvent,
    TurnCommittedEvent,
    WelcomeEvent,
)
from arena.sdk._session import Session
from arena.sdk.errors import (
    ActionRejectedError,
    HandshakeError,
    HeartbeatTimeoutError,
    MalformedEnvelopeError,
    MatchAbortedError,
    MatchNotFoundError,
    ProtocolError,
    RateLimitedError,
    SchemaVersionError,
    SdkError,
    SeatTakenError,
    ServerError,
    UnauthorizedError,
    close_code_to_error,
)
from arena.sdk.testing import LocalSession

__all__ = [
    "Session",
    "LocalSession",
    "connect",
    "_run_session",
    "SdkError",
    "ProtocolError",
    "SchemaVersionError",
    "UnauthorizedError",
    "MatchNotFoundError",
    "SeatTakenError",
    "HeartbeatTimeoutError",
    "MalformedEnvelopeError",
    "RateLimitedError",
    "ServerError",
    "MatchAbortedError",
    "ActionRejectedError",
    "HandshakeError",
    "close_code_to_error",
    "ObservationEvent",
    "TurnCommittedEvent",
    "MatchFinishedEvent",
    "MatchAbortedEvent",
    "MatchStateEvent",
    "WelcomeEvent",
    "ErrorEvent",
    "SdkEvent",
]
