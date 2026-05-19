"""Exception hierarchy for arena.sdk."""
from __future__ import annotations

from collections.abc import Sequence


class SdkError(Exception):
    """Base class for all arena.sdk errors."""


class ProtocolError(SdkError):
    """Close-code-level wire protocol error."""

    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"Protocol error {code}: {reason}")


class SchemaVersionError(ProtocolError):
    """Close code 4400 — no mutually supported schema_version."""


class UnauthorizedError(ProtocolError):
    """Close code 4401 — reserved for v2 auth."""


class MatchNotFoundError(ProtocolError):
    """Close code 4410 — match_id not found or expired."""


class SeatTakenError(ProtocolError):
    """Close code 4409 — seat already has a live connection."""


class HeartbeatTimeoutError(ProtocolError):
    """Close code 4408 — two consecutive missed pongs."""


class MalformedEnvelopeError(ProtocolError):
    """Close code 4422 — envelope failed validation."""


class RateLimitedError(ProtocolError):
    """Close code 4429 — connection or match-creation rate cap hit."""


class ServerError(ProtocolError):
    """Close code 4500 — internal server failure."""


class MatchAbortedError(SdkError):
    """Raised by connect() when the match aborts before finishing."""

    def __init__(self, abort_body: object, transcript: object) -> None:
        self.abort_body = abort_body
        self.transcript = transcript
        super().__init__(f"Match aborted: {abort_body}")


class ActionRejectedError(SdkError):
    """Raised by send_action() when the server returns action_rejected (retries exhausted)."""

    def __init__(self, error_payload: object, retries_remaining: int) -> None:
        self.error_payload = error_payload
        self.retries_remaining = retries_remaining
        super().__init__(f"Action rejected: {error_payload}")


class HandshakeError(SdkError):
    """Raised when hello/welcome handshake fails."""


CLOSE_CODE_MAP: dict[int, type[ProtocolError]] = {
    4400: SchemaVersionError,
    4401: UnauthorizedError,
    4408: HeartbeatTimeoutError,
    4409: SeatTakenError,
    4410: MatchNotFoundError,
    4422: MalformedEnvelopeError,
    4429: RateLimitedError,
    4500: ServerError,
}


def close_code_to_error(code: int, reason: str) -> ProtocolError:
    """Map a WebSocket close code to the appropriate ProtocolError subclass."""
    cls = CLOSE_CODE_MAP.get(code, ProtocolError)
    return cls(code, reason)


__all__: Sequence[str] = [
    "ActionRejectedError",
    "CLOSE_CODE_MAP",
    "HandshakeError",
    "HeartbeatTimeoutError",
    "MalformedEnvelopeError",
    "MatchAbortedError",
    "MatchNotFoundError",
    "ProtocolError",
    "RateLimitedError",
    "SchemaVersionError",
    "SdkError",
    "SeatTakenError",
    "ServerError",
    "UnauthorizedError",
    "close_code_to_error",
]
