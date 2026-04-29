"""Pydantic v2 body models for every WebSocket message type (§8 of NETWORK_PROTOCOL.md)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from arena.adapters.in_process import (
    ActionResponsePayload,
    DomainErrorPayload,
    ObservationRequestPayload,
)
from arena.runtime.payloads import RuntimeAbortPayload, RuntimeTranscriptPayload

# ---------------------------------------------------------------------------
# Message type string constants
# ---------------------------------------------------------------------------

MSG_HELLO = "hello"
MSG_WELCOME = "welcome"
MSG_MATCH_STATE = "match_state"
MSG_OBSERVATION_REQUEST = "observation_request"
MSG_ACTION_RESPONSE = "action_response"
MSG_ACTION_REJECTED = "action_rejected"
MSG_TURN_COMMITTED = "turn_committed"
MSG_MATCH_FINISHED = "match_finished"
MSG_MATCH_ABORTED = "match_aborted"
MSG_PING = "ping"
MSG_PONG = "pong"
MSG_ERROR = "error"

# ---------------------------------------------------------------------------
# Shared player payload (mirrors RuntimePlayerPayload without importing runtime)
# ---------------------------------------------------------------------------


class PlayerInfoBody(BaseModel):
    """Minimal player identity used inside welcome and match_state bodies."""

    model_config = ConfigDict(extra="ignore", strict=True)

    player_id: str = Field(min_length=1)
    label: str | None = None
    seat: int = Field(ge=0)


# ---------------------------------------------------------------------------
# §8.1 hello (Client → Server)
# ---------------------------------------------------------------------------


class HelloBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    client_name: str = Field(min_length=1)
    client_version: str = Field(min_length=1)
    supported_schema_versions: list[int] = Field(min_length=1)
    auth: Any = None
    requested_seat: int = Field(ge=0)
    resume_token: str | None = None


# ---------------------------------------------------------------------------
# §8.2 welcome (Server → Client)
# ---------------------------------------------------------------------------


class WelcomeBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    game_schema_version: int = Field(ge=1)
    seat: int = Field(ge=0)
    lifecycle: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    negotiated_schema_version: int = Field(ge=1)
    resume_token: str | None = None
    per_turn_deadline_ms: int = Field(ge=0)
    per_action_retry_budget: int = Field(ge=0)
    disconnect_grace_ms: int = Field(ge=0)
    players: list[PlayerInfoBody]
    match_config: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# §8.3 match_state (Server → Client, broadcast)
# ---------------------------------------------------------------------------


class MatchStateBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    lifecycle: str = Field(min_length=1)
    current_seat: int | None = None
    turn_count: int = Field(ge=0)
    result: dict[str, Any] | None = None
    abort: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# §8.4 observation_request (Server → Client)
# ---------------------------------------------------------------------------


class ObservationRequestBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    observation_request: ObservationRequestPayload
    deadline_ms: int = Field(ge=0)


# ---------------------------------------------------------------------------
# §8.5 action_response (Client → Server)
# ---------------------------------------------------------------------------


class ActionResponseBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    action_response: ActionResponsePayload


# ---------------------------------------------------------------------------
# §8.6 action_rejected (Server → Client)
# ---------------------------------------------------------------------------


class ActionRejectedBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    turn_id: str = Field(min_length=1)
    error: DomainErrorPayload
    retries_remaining: int = Field(ge=0)


# ---------------------------------------------------------------------------
# §8.7 turn_committed (Server → Client, broadcast)
# ---------------------------------------------------------------------------


class TurnCommittedBody(BaseModel):
    """Body for turn_committed; turn_record, post_snapshot, events are game-specific JSON."""

    model_config = ConfigDict(extra="ignore", strict=True)

    turn_record: dict[str, Any]
    post_snapshot: dict[str, Any]
    events: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# §8.8 match_finished (Server → Client, broadcast)
# ---------------------------------------------------------------------------


class MatchFinishedBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    result: dict[str, Any]
    transcript: RuntimeTranscriptPayload


# ---------------------------------------------------------------------------
# §8.9 match_aborted (Server → Client, broadcast)
# ---------------------------------------------------------------------------


class MatchAbortedBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    abort: RuntimeAbortPayload
    transcript: RuntimeTranscriptPayload


# ---------------------------------------------------------------------------
# §8.10 ping / pong (bidirectional)
# ---------------------------------------------------------------------------


class PingBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    nonce: str = Field(min_length=1)


class PongBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    nonce: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# §8.11 error (Server → Client, non-terminal)
# ---------------------------------------------------------------------------


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


__all__: Sequence[str] = [
    "MSG_ACTION_REJECTED",
    "MSG_ACTION_RESPONSE",
    "MSG_ERROR",
    "MSG_HELLO",
    "MSG_MATCH_ABORTED",
    "MSG_MATCH_FINISHED",
    "MSG_MATCH_STATE",
    "MSG_OBSERVATION_REQUEST",
    "MSG_PING",
    "MSG_PONG",
    "MSG_TURN_COMMITTED",
    "MSG_WELCOME",
    "ActionRejectedBody",
    "ActionResponseBody",
    "ErrorBody",
    "HelloBody",
    "MatchAbortedBody",
    "MatchFinishedBody",
    "MatchStateBody",
    "ObservationRequestBody",
    "PingBody",
    "PlayerInfoBody",
    "PongBody",
    "TurnCommittedBody",
    "WelcomeBody",
]
