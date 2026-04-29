"""Discriminated-union envelope models for the WebSocket wire protocol (§6).

Each concrete envelope class carries a Literal `type` field used as the discriminator.
`WireEnvelope` is the annotated union; `decode_envelope` dispatches by type string.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from arena.adapters.websocket.messages import (
    MSG_ACTION_REJECTED,
    MSG_ACTION_RESPONSE,
    MSG_ERROR,
    MSG_HELLO,
    MSG_MATCH_ABORTED,
    MSG_MATCH_FINISHED,
    MSG_MATCH_STATE,
    MSG_OBSERVATION_REQUEST,
    MSG_PING,
    MSG_PONG,
    MSG_TURN_COMMITTED,
    MSG_WELCOME,
    ActionRejectedBody,
    ActionResponseBody,
    ErrorBody,
    HelloBody,
    MatchAbortedBody,
    MatchFinishedBody,
    MatchStateBody,
    ObservationRequestBody,
    PingBody,
    PongBody,
    TurnCommittedBody,
    WelcomeBody,
)


class _EnvelopeBase(BaseModel):
    """Common envelope fields present on every WebSocket message (§6)."""

    model_config = ConfigDict(extra="ignore", strict=True)

    schema_version: int = Field(ge=1)
    match_id: str | None = None
    seat: int | None = None
    turn_id: str | None = None


class HelloEnvelope(_EnvelopeBase):
    type: Literal["hello"] = MSG_HELLO
    payload: HelloBody


class WelcomeEnvelope(_EnvelopeBase):
    type: Literal["welcome"] = MSG_WELCOME
    payload: WelcomeBody


class MatchStateEnvelope(_EnvelopeBase):
    type: Literal["match_state"] = MSG_MATCH_STATE
    payload: MatchStateBody


class ObservationRequestEnvelope(_EnvelopeBase):
    type: Literal["observation_request"] = MSG_OBSERVATION_REQUEST
    payload: ObservationRequestBody


class ActionResponseEnvelope(_EnvelopeBase):
    type: Literal["action_response"] = MSG_ACTION_RESPONSE
    payload: ActionResponseBody


class ActionRejectedEnvelope(_EnvelopeBase):
    type: Literal["action_rejected"] = MSG_ACTION_REJECTED
    payload: ActionRejectedBody


class TurnCommittedEnvelope(_EnvelopeBase):
    type: Literal["turn_committed"] = MSG_TURN_COMMITTED
    payload: TurnCommittedBody


class MatchFinishedEnvelope(_EnvelopeBase):
    type: Literal["match_finished"] = MSG_MATCH_FINISHED
    payload: MatchFinishedBody


class MatchAbortedEnvelope(_EnvelopeBase):
    type: Literal["match_aborted"] = MSG_MATCH_ABORTED
    payload: MatchAbortedBody


class PingEnvelope(_EnvelopeBase):
    type: Literal["ping"] = MSG_PING
    payload: PingBody


class PongEnvelope(_EnvelopeBase):
    type: Literal["pong"] = MSG_PONG
    payload: PongBody


class ErrorEnvelope(_EnvelopeBase):
    type: Literal["error"] = MSG_ERROR
    payload: ErrorBody


WireEnvelope = Annotated[
    Union[
        HelloEnvelope,
        WelcomeEnvelope,
        MatchStateEnvelope,
        ObservationRequestEnvelope,
        ActionResponseEnvelope,
        ActionRejectedEnvelope,
        TurnCommittedEnvelope,
        MatchFinishedEnvelope,
        MatchAbortedEnvelope,
        PingEnvelope,
        PongEnvelope,
        ErrorEnvelope,
    ],
    Field(discriminator="type"),
]

_ENVELOPE_TYPES: dict[str, type] = {
    MSG_HELLO: HelloEnvelope,
    MSG_WELCOME: WelcomeEnvelope,
    MSG_MATCH_STATE: MatchStateEnvelope,
    MSG_OBSERVATION_REQUEST: ObservationRequestEnvelope,
    MSG_ACTION_RESPONSE: ActionResponseEnvelope,
    MSG_ACTION_REJECTED: ActionRejectedEnvelope,
    MSG_TURN_COMMITTED: TurnCommittedEnvelope,
    MSG_MATCH_FINISHED: MatchFinishedEnvelope,
    MSG_MATCH_ABORTED: MatchAbortedEnvelope,
    MSG_PING: PingEnvelope,
    MSG_PONG: PongEnvelope,
    MSG_ERROR: ErrorEnvelope,
}


def decode_envelope(obj: dict) -> WireEnvelope:  # type: ignore[return]
    """Dispatch a raw dict to the correct envelope model by its `type` field.

    Callers are responsible for raising WireDecodeError / UnknownMessageType on
    bad input; this function only performs Pydantic validation.
    """
    from arena.adapters.websocket.errors import UnknownMessageType, WireDecodeError

    msg_type = obj.get("type")
    if msg_type is None:
        raise WireDecodeError("Envelope is missing required field 'type'.")

    envelope_cls = _ENVELOPE_TYPES.get(msg_type)
    if envelope_cls is None:
        raise UnknownMessageType(msg_type)

    try:
        return envelope_cls.model_validate(obj)
    except Exception as exc:
        raise WireDecodeError(f"Envelope validation failed: {exc}") from exc


__all__: Sequence[str] = [
    "ActionRejectedEnvelope",
    "ActionResponseEnvelope",
    "ErrorEnvelope",
    "HelloEnvelope",
    "MatchAbortedEnvelope",
    "MatchFinishedEnvelope",
    "MatchStateEnvelope",
    "ObservationRequestEnvelope",
    "PingEnvelope",
    "PongEnvelope",
    "TurnCommittedEnvelope",
    "WelcomeEnvelope",
    "WireEnvelope",
    "decode_envelope",
]
