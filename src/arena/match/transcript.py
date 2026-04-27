"""JSON-safe local match transcript payloads and loaders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Generic, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import Draw, RuleResult, Win
from arena.core.serializer import JSONMapping, SnapshotEnvelope
from arena.core.types import Seat
from arena.match.local_match import LocalMatch, apply_match_action, start_match

ConfigT = TypeVar("ConfigT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
ResultT = TypeVar("ResultT", bound=RuleResult)

MATCH_TRANSCRIPT_SCHEMA_VERSION = 1


class MatchEventPayload(BaseModel):
    """JSON-safe payload for a single recorded domain event."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class MatchResultPayload(BaseModel):
    """JSON-safe payload for a recorded rule result."""

    model_config = ConfigDict(extra="forbid", strict=True)

    result_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class MatchTurnPayload(BaseModel):
    """JSON-safe payload for one accepted match turn."""

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int
    action: JSONMapping
    events: list[MatchEventPayload]
    result: MatchResultPayload | None
    post_snapshot: SnapshotEnvelope


class MatchTranscriptPayload(BaseModel):
    """JSON-safe payload for a complete local match transcript."""

    model_config = ConfigDict(extra="forbid", strict=True)

    game_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    config: JSONMapping
    initial_snapshot: SnapshotEnvelope
    turns: list[MatchTurnPayload]


@dataclass(frozen=True)
class LoadedMatchTurn(Generic[StateT, ActionT]):
    """Typed turn data rehydrated from a match transcript."""

    seat: Seat
    action: ActionT
    event_payloads: tuple[JSONMapping, ...]
    result: RuleResult | None
    result_payload: JSONMapping | None
    post_state: StateT
    post_snapshot: SnapshotEnvelope


@dataclass(frozen=True)
class LoadedMatchTranscript(Generic[ConfigT, StateT, ActionT, ObservationT, ResultT]):
    """Typed transcript data rehydrated from a JSON-safe payload."""

    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT]
    game_id: str
    schema_version: int
    config: ConfigT
    initial_snapshot: SnapshotEnvelope
    initial_state: StateT
    latest_state: StateT
    turns: tuple[LoadedMatchTurn[StateT, ActionT], ...]


def dump_match_transcript(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
) -> JSONMapping:
    """Serialize a local match transcript into a JSON-safe mapping."""

    payload = MatchTranscriptPayload(
        game_id=match.definition.game_id,
        schema_version=MATCH_TRANSCRIPT_SCHEMA_VERSION,
        config=match.definition.serializer.dump_config(match.config),
        initial_snapshot=match.initial_snapshot,
        turns=[
            MatchTurnPayload(
                seat=turn.seat,
                action=match.definition.serializer.dump_action(turn.action),
                events=[
                    _dump_domain_event(event)
                    for event in turn.events
                ],
                result=_dump_rule_result(turn.result),
                post_snapshot=turn.post_snapshot,
            )
            for turn in match.turns
        ],
    )
    return payload.model_dump(mode="json")


def load_match_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
) -> LoadedMatchTranscript[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Rehydrate a transcript payload into typed match data."""

    transcript_payload = MatchTranscriptPayload.model_validate(payload)
    _ensure_definition_matches_payload(definition.game_id, transcript_payload)

    config = cast(
        ConfigT,
        definition.serializer.load_config(transcript_payload.config),
    )
    initial_state = cast(
        StateT,
        definition.serializer.load_state(transcript_payload.initial_snapshot.state),
    )

    loaded_turns = tuple(
        LoadedMatchTurn[StateT, ActionT](
            seat=turn_payload.seat,
            action=cast(
                ActionT,
                definition.serializer.load_action(turn_payload.action),
            ),
            event_payloads=tuple(
                event_payload.model_dump(mode="json") for event_payload in turn_payload.events
            ),
            result=_load_rule_result(turn_payload.result),
            result_payload=(
                turn_payload.result.model_dump(mode="json")
                if turn_payload.result is not None
                else None
            ),
            post_state=cast(
                StateT,
                definition.serializer.load_state(turn_payload.post_snapshot.state),
            ),
            post_snapshot=turn_payload.post_snapshot,
        )
        for turn_payload in transcript_payload.turns
    )

    latest_state = loaded_turns[-1].post_state if loaded_turns else initial_state

    return LoadedMatchTranscript(
        definition=definition,
        game_id=transcript_payload.game_id,
        schema_version=transcript_payload.schema_version,
        config=config,
        initial_snapshot=transcript_payload.initial_snapshot,
        initial_state=initial_state,
        latest_state=latest_state,
        turns=loaded_turns,
    )


def validate_match_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
) -> LoadedMatchTranscript[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Validate a transcript by replaying it against a fresh local match."""

    loaded_transcript = load_match_transcript(definition, payload)
    replay_match = start_match(definition, loaded_transcript.config)

    _ensure_snapshot_matches(
        expected=loaded_transcript.initial_snapshot,
        actual=replay_match.initial_snapshot,
        context="Initial",
    )
    _ensure_state_matches(
        expected=loaded_transcript.initial_state,
        actual=replay_match.state,
        context="Initial",
    )

    for turn_index, loaded_turn in enumerate(loaded_transcript.turns, start=1):
        replay_match = apply_match_action(replay_match, loaded_turn.seat, loaded_turn.action)
        generated_turn = replay_match.turns[-1]

        _ensure_state_matches(
            expected=loaded_turn.post_state,
            actual=generated_turn.post_state,
            context=f"Turn {turn_index}",
        )
        _ensure_snapshot_matches(
            expected=loaded_turn.post_snapshot,
            actual=generated_turn.post_snapshot,
            context=f"Turn {turn_index}",
        )
        _ensure_event_payloads_match(
            expected_payloads=loaded_turn.event_payloads,
            actual_events=generated_turn.events,
            context=f"Turn {turn_index}",
        )
        _ensure_result_matches(
            expected_result=loaded_turn.result,
            expected_payload=loaded_turn.result_payload,
            actual_result=generated_turn.result,
            context=f"Turn {turn_index}",
        )

    return loaded_transcript


def _dump_domain_event(event: DomainEvent) -> MatchEventPayload:
    payload = _dump_dataclass_fields(event)
    return MatchEventPayload(event_type=event.event_type, payload=payload)


def _dump_rule_result(result: RuleResult | None) -> MatchResultPayload | None:
    if result is None:
        return None

    payload = _dump_dataclass_fields(result)
    return MatchResultPayload(result_type=result.result_type, payload=payload)


def _dump_dataclass_fields(value: object) -> JSONMapping:
    if not is_dataclass(value):
        raise TypeError(f"Expected a dataclass instance, got {type(value).__name__}.")

    return {field.name: getattr(value, field.name) for field in fields(value)}


def _load_rule_result(result_payload: MatchResultPayload | None) -> RuleResult | None:
    if result_payload is None:
        return None

    if result_payload.result_type == "Win":
        return Win(seat=result_payload.payload["seat"])
    if result_payload.result_type == "Draw":
        return Draw()

    return None


def _ensure_definition_matches_payload(game_id: str, payload: MatchTranscriptPayload) -> None:
    if payload.game_id != game_id:
        raise ValueError(
            f"Transcript game_id {payload.game_id!r} does not match definition {game_id!r}."
        )

    if payload.initial_snapshot.game_id != game_id:
        raise ValueError(
            "Transcript initial snapshot game_id does not match the supplied definition."
        )

    for turn_payload in payload.turns:
        if turn_payload.post_snapshot.game_id != game_id:
            raise ValueError(
                "Transcript turn snapshot game_id does not match the supplied definition."
            )


def _ensure_snapshot_matches(
    *,
    expected: SnapshotEnvelope,
    actual: SnapshotEnvelope,
    context: str,
) -> None:
    if actual.game_id != expected.game_id:
        raise ValueError(
            (
                f"{context} snapshot game_id mismatch: "
                f"expected {expected.game_id!r}, got {actual.game_id!r}."
            )
        )

    if actual.schema_version != expected.schema_version:
        raise ValueError(
            (
                f"{context} snapshot schema_version mismatch: "
                f"expected {expected.schema_version!r}, got {actual.schema_version!r}."
            )
        )

    if actual.config != expected.config:
        raise ValueError(
            (
                f"{context} snapshot config mismatch: "
                f"expected {expected.config!r}, got {actual.config!r}."
            )
        )

    if actual.state != expected.state:
        raise ValueError(
            f"{context} snapshot state mismatch: expected {expected.state!r}, got {actual.state!r}."
        )


def _ensure_state_matches(*, expected: object, actual: object, context: str) -> None:
    if actual != expected:
        raise ValueError(f"{context} state mismatch: expected {expected!r}, got {actual!r}.")


def _ensure_event_payloads_match(
    *,
    expected_payloads: Sequence[JSONMapping],
    actual_events: Sequence[DomainEvent],
    context: str,
) -> None:
    actual_payloads = tuple(
        _dump_domain_event(event).model_dump(mode="json")
        for event in actual_events
    )
    expected_payloads_tuple = tuple(expected_payloads)
    if actual_payloads != expected_payloads_tuple:
        raise ValueError(
            (
                f"{context} event payload mismatch: "
                f"expected {expected_payloads_tuple!r}, got {actual_payloads!r}."
            )
        )


def _ensure_result_matches(
    *,
    expected_result: RuleResult | None,
    expected_payload: JSONMapping | None,
    actual_result: RuleResult | None,
    context: str,
) -> None:
    actual_payload = (
        _dump_rule_result(actual_result).model_dump(mode="json")
        if actual_result is not None
        else None
    )
    if actual_result != expected_result:
        raise ValueError(
            f"{context} result mismatch: expected {expected_result!r}, got {actual_result!r}."
        )
    if actual_payload != expected_payload:
        raise ValueError(
            (
                f"{context} result payload mismatch: "
                f"expected {expected_payload!r}, got {actual_payload!r}."
            )
        )


__all__: Sequence[str] = [
    "LoadedMatchTranscript",
    "LoadedMatchTurn",
    "MATCH_TRANSCRIPT_SCHEMA_VERSION",
    "MatchEventPayload",
    "MatchResultPayload",
    "MatchTranscriptPayload",
    "MatchTurnPayload",
    "dump_match_transcript",
    "load_match_transcript",
    "validate_match_transcript",
]
