"""JSON-safe runtime envelopes for transcripts, CLI output, and future UI use."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields, is_dataclass
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import RuleResult
from arena.core.serializer import JSONMapping, SnapshotEnvelope
from arena.match.transcript import (
    LoadedMatchTranscript,
    dump_match_transcript,
    validate_match_transcript,
)
from arena.runtime.models import (
    AbortMetadata,
    MatchAborted,
    MatchCreated,
    MatchFinished,
    MatchStarted,
    PlayerRecord,
    RuntimeEvent,
    TurnAccepted,
    TurnRequested,
)
from arena.runtime.session import MatchSession

ConfigT = TypeVar("ConfigT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
ResultT = TypeVar("ResultT", bound=RuleResult)

RUNTIME_TRANSCRIPT_SCHEMA_VERSION = 1


class RuntimePlayerPayload(BaseModel):
    """JSON-safe runtime player and seat assignment."""

    model_config = ConfigDict(extra="forbid", strict=True)

    player_id: str = Field(min_length=1)
    seat: int = Field(ge=0)
    label: str | None = None


class RuntimeAbortPayload(BaseModel):
    """JSON-safe runtime abort metadata."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str = Field(min_length=1)
    message: str = Field(min_length=1)
    cause_type: str | None = None
    cause_message: str | None = None


class RuntimeEventPayload(BaseModel):
    """JSON-safe runtime event record."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class RuntimeResultPayload(BaseModel):
    """JSON-safe current game result summary for status payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)

    result_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class RuntimeSessionStatusPayload(BaseModel):
    """JSON-safe session status envelope for CLI and UI consumers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    lifecycle: str = Field(min_length=1)
    players: list[RuntimePlayerPayload]
    current_seat: int | None
    turn_count: int
    result: RuntimeResultPayload | None
    latest_snapshot: SnapshotEnvelope | None
    abort: RuntimeAbortPayload | None


class RuntimeTranscriptPayload(BaseModel):
    """JSON-safe runtime transcript envelope around a local match transcript."""

    model_config = ConfigDict(extra="forbid", strict=True)

    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    lifecycle: str = Field(min_length=1)
    players: list[RuntimePlayerPayload]
    events: list[RuntimeEventPayload]
    abort: RuntimeAbortPayload | None
    match_transcript: JSONMapping | None


def dump_session_status(
    session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
) -> JSONMapping:
    """Dump the current runtime session status as a JSON-safe mapping."""

    local_match = session.local_match
    current_seat = None
    latest_snapshot = None
    result = None
    turn_count = 0

    if local_match is not None:
        turn_count = len(local_match.turns)
        latest_snapshot = (
            local_match.turns[-1].post_snapshot
            if local_match.turns
            else local_match.initial_snapshot
        )
        if not local_match.rules_engine.is_terminal(local_match.state):
            current_seat = local_match.rules_engine.current_seat(local_match.state)
        result = _dump_rule_result(local_match.rules_engine.result(local_match.state))

    payload = RuntimeSessionStatusPayload(
        match_id=session.match_id,
        game_id=session.definition.game_id,
        lifecycle=session.lifecycle.value,
        players=[_dump_player(player) for player in session.players],
        current_seat=current_seat,
        turn_count=turn_count,
        result=result,
        latest_snapshot=latest_snapshot,
        abort=_dump_abort(session.abort),
    )
    return payload.model_dump(mode="json")


def dump_runtime_transcript(
    session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
) -> JSONMapping:
    """Dump a runtime transcript envelope without validating replay."""

    payload = RuntimeTranscriptPayload(
        match_id=session.match_id,
        game_id=session.definition.game_id,
        schema_version=RUNTIME_TRANSCRIPT_SCHEMA_VERSION,
        lifecycle=session.lifecycle.value,
        players=[_dump_player(player) for player in session.players],
        events=[_dump_runtime_event(event) for event in session.events],
        abort=_dump_abort(session.abort),
        match_transcript=(
            dump_match_transcript(session.local_match)
            if session.local_match is not None
            else None
        ),
    )
    return payload.model_dump(mode="json")


def validate_runtime_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
) -> LoadedMatchTranscript[ConfigT, StateT, ActionT, ObservationT, ResultT] | None:
    """Validate the wrapped local match transcript when one is present."""

    runtime_payload = RuntimeTranscriptPayload.model_validate(payload)
    if runtime_payload.schema_version != RUNTIME_TRANSCRIPT_SCHEMA_VERSION:
        raise ValueError(
            "Runtime transcript schema_version "
            f"{runtime_payload.schema_version!r} does not match "
            f"{RUNTIME_TRANSCRIPT_SCHEMA_VERSION!r}."
        )
    if runtime_payload.game_id != definition.game_id:
        raise ValueError(
            f"Runtime transcript game_id {runtime_payload.game_id!r} "
            f"does not match definition {definition.game_id!r}."
        )
    if runtime_payload.match_transcript is None:
        return None
    return validate_match_transcript(definition, runtime_payload.match_transcript)


def _dump_player(player: PlayerRecord) -> RuntimePlayerPayload:
    return RuntimePlayerPayload(
        player_id=player.player_id,
        seat=player.seat,
        label=player.label,
    )


def _dump_abort(abort: AbortMetadata | None) -> RuntimeAbortPayload | None:
    if abort is None:
        return None
    return RuntimeAbortPayload(
        reason=abort.reason.value,
        message=abort.message,
        cause_type=abort.cause_type,
        cause_message=abort.cause_message,
    )


def _dump_runtime_event(event: RuntimeEvent) -> RuntimeEventPayload:
    payload: JSONMapping
    if isinstance(event, MatchCreated):
        payload = {
            "players": [
                _dump_player(player).model_dump(mode="json") for player in event.players
            ]
        }
    elif isinstance(event, MatchStarted | MatchFinished):
        payload = {}
    elif isinstance(event, TurnRequested):
        payload = {"seat": event.seat}
    elif isinstance(event, TurnAccepted):
        payload = {"seat": event.seat, "turn_index": event.turn_index}
    elif isinstance(event, MatchAborted):
        payload = {"abort": _dump_abort(event.abort).model_dump(mode="json")}
    else:
        payload = {}

    return RuntimeEventPayload(event_type=event.event_type, payload=payload)


def _dump_rule_result(result: RuleResult | None) -> RuntimeResultPayload | None:
    if result is None:
        return None
    if not is_dataclass(result):
        return RuntimeResultPayload(result_type=result.result_type)
    return RuntimeResultPayload(
        result_type=result.result_type,
        payload={field.name: getattr(result, field.name) for field in fields(result)},
    )


__all__: Sequence[str] = [
    "RUNTIME_TRANSCRIPT_SCHEMA_VERSION",
    "RuntimeAbortPayload",
    "RuntimeEventPayload",
    "RuntimePlayerPayload",
    "RuntimeResultPayload",
    "RuntimeSessionStatusPayload",
    "RuntimeTranscriptPayload",
    "dump_runtime_transcript",
    "dump_session_status",
    "validate_runtime_transcript",
]
