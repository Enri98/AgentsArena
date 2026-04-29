"""Pure typed wire-envelope contract for WebSocket transport.

No I/O. No networking. Pydantic v2 models and JSON encode/decode helpers only.
Import path: arena.adapters.websocket
"""

from __future__ import annotations

from collections.abc import Sequence

from arena.adapters.websocket.codec import WIRE_SCHEMA_VERSION, dumps, loads
from arena.adapters.websocket.envelope import (
    ActionRejectedEnvelope,
    ActionResponseEnvelope,
    ErrorEnvelope,
    HelloEnvelope,
    MatchAbortedEnvelope,
    MatchFinishedEnvelope,
    MatchStateEnvelope,
    ObservationRequestEnvelope,
    PingEnvelope,
    PongEnvelope,
    TurnCommittedEnvelope,
    WelcomeEnvelope,
    WireEnvelope,
    decode_envelope,
)
from arena.adapters.websocket.errors import (
    SchemaVersionMismatch,
    UnknownMessageType,
    WireDecodeError,
    WireProtocolError,
)
from arena.adapters.websocket.messages import (
    ActionRejectedBody,
    ActionResponseBody,
    ErrorBody,
    HelloBody,
    MatchAbortedBody,
    MatchFinishedBody,
    MatchStateBody,
    ObservationRequestBody,
    PingBody,
    PlayerInfoBody,
    PongBody,
    TurnCommittedBody,
    WelcomeBody,
)

__all__: Sequence[str] = [
    "WIRE_SCHEMA_VERSION",
    "ActionRejectedBody",
    "ActionRejectedEnvelope",
    "ActionResponseBody",
    "ActionResponseEnvelope",
    "ErrorBody",
    "ErrorEnvelope",
    "HelloBody",
    "HelloEnvelope",
    "MatchAbortedBody",
    "MatchAbortedEnvelope",
    "MatchFinishedBody",
    "MatchFinishedEnvelope",
    "MatchStateBody",
    "MatchStateEnvelope",
    "ObservationRequestBody",
    "ObservationRequestEnvelope",
    "PingBody",
    "PingEnvelope",
    "PlayerInfoBody",
    "PongBody",
    "PongEnvelope",
    "SchemaVersionMismatch",
    "TurnCommittedBody",
    "TurnCommittedEnvelope",
    "UnknownMessageType",
    "WelcomeBody",
    "WelcomeEnvelope",
    "WireDecodeError",
    "WireEnvelope",
    "WireProtocolError",
    "decode_envelope",
    "dumps",
    "loads",
]
