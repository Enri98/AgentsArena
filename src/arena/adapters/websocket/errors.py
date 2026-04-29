"""Typed wire-layer exceptions for the WebSocket adapter."""

from __future__ import annotations

from collections.abc import Sequence


class WireProtocolError(Exception):
    """Base class for all wire-layer protocol errors."""


class WireDecodeError(WireProtocolError):
    """Raised when a raw input cannot be decoded into a valid envelope."""


class SchemaVersionMismatch(WireProtocolError):
    """Raised when the envelope schema_version is not supported."""

    def __init__(self, received: int, expected: int) -> None:
        self.received = received
        self.expected = expected
        super().__init__(
            f"Unsupported schema_version {received!r}; expected {expected!r}."
        )


class UnknownMessageType(WireProtocolError):
    """Raised when the envelope type field names an unrecognised message."""

    def __init__(self, message_type: str) -> None:
        self.message_type = message_type
        super().__init__(f"Unknown message type {message_type!r}.")


__all__: Sequence[str] = [
    "SchemaVersionMismatch",
    "UnknownMessageType",
    "WireDecodeError",
    "WireProtocolError",
]
