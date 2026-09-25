"""JSON-safe local match transcript payloads and loaders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Generic, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from arena.core.actions import Action
from arena.core.chance import dump_chance_outcome, is_chance_node, load_chance_outcome
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent, event_payload_visible_to
from arena.core.exceptions import ArenaCoreError
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.public_view import (
    Viewer,
    check_viewer,
    dump_chance_outcome_for_viewer,
    dump_config_for_viewer,
)
from arena.core.results import Draw, RuleResult, Win
from arena.core.serializer import JSONMapping, SnapshotEnvelope
from arena.core.types import Seat
from arena.match.local_match import (
    TURN_KIND_ACTION,
    TURN_KIND_CHANCE,
    TURN_KIND_JOINT,
    LocalMatch,
    apply_match_action,
    apply_match_chance,
    apply_match_joint_action,
    build_snapshot_for_viewer,
    start_replay_match,
)

ConfigT = TypeVar("ConfigT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
ResultT = TypeVar("ResultT", bound=RuleResult)

#: Bumped to 2 in Phase 37: turns gained a ``kind``, and a chance turn carries
#: no seat and no action. That is a shape change an older reader cannot handle,
#: so it is a version bump rather than an additive field.
#:
#: Bumped to 3 in Phase 38: a transcript declares its ``view`` (full, one seat's,
#: or the public's) and events record their audience. A seat-view transcript of
#: a hidden-information game omits what that seat may not see, so a reader must
#: be able to tell which kind it holds.
#:
#: Bumped to 4 in Phase 41: a joint turn (several seats acting at once) carries
#: an ``actions`` map instead of one seat and one action.
MATCH_TRANSCRIPT_SCHEMA_VERSION = 4

#: Transcript versions this loader accepts. A v1 transcript predates chance
#: nodes; v1 and v2 predate views, and are always full transcripts; v1-v3
#: predate joint turns.
SUPPORTED_MATCH_TRANSCRIPT_SCHEMA_VERSIONS = (1, 2, 3, 4)

#: The unredacted transcript: everything, including every seat's private state.
VIEW_FULL = "full"
#: One seat's transcript: only what that seat was entitled to see.
VIEW_SEAT = "seat"
#: The public transcript: what a spectator may see.
VIEW_PUBLIC = "public"

TranscriptView = Literal["full", "seat", "public"]


class MatchEventPayload(BaseModel):
    """JSON-safe payload for a single recorded domain event."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)
    #: Phase 38. A non-public event is delivered only to ``audience``. Defaults
    #: keep an older transcript, whose events were all public, valid, and a public
    #: event is serialized without either key, so payloads of games with no
    #: private events are exactly what they were before.
    is_public: bool = True
    audience: list[int] | None = None

    @model_serializer(mode="wrap")
    def _omit_public_marker(self, handler: Any) -> Any:
        data = handler(self)
        if self.is_public:
            data.pop("is_public", None)
            data.pop("audience", None)
        return data


class MatchResultPayload(BaseModel):
    """JSON-safe payload for a recorded rule result."""

    model_config = ConfigDict(extra="forbid", strict=True)

    result_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class MatchTurnPayload(BaseModel):
    """JSON-safe payload for one match turn.

    ``seat`` and ``action`` are null on a chance turn: no seat chose it. It
    carries ``outcome`` instead — the recorded result replay applies, so a
    transcript validates without the seed. They are null on a joint turn too
    (Phase 41), which carries ``actions``: each acting seat (as a string key, a
    JSON object's keys being strings) mapped to its action. Every new field
    defaults so older transcripts still validate, and ``actions`` is omitted
    when absent, so a sequential turn serializes exactly as it did in v3.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int | None = None
    action: JSONMapping | None = None
    events: list[MatchEventPayload]
    result: MatchResultPayload | None
    post_snapshot: SnapshotEnvelope
    kind: str = TURN_KIND_ACTION
    outcome: JSONMapping | None = None
    actions: dict[str, JSONMapping] | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_actions(self, handler: Any) -> Any:
        data = handler(self)
        if self.actions is None:
            data.pop("actions", None)
        return data


class MatchTranscriptPayload(BaseModel):
    """JSON-safe payload for a complete local match transcript."""

    model_config = ConfigDict(extra="forbid", strict=True)

    game_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    config: JSONMapping
    initial_snapshot: SnapshotEnvelope
    turns: list[MatchTurnPayload]
    #: Phase 38: which view this is. Only a ``"full"`` transcript can be
    #: replayed; a redacted one lacks the hidden state replay needs.
    view: TranscriptView = VIEW_FULL
    #: The seat a ``"seat"`` view belongs to; null otherwise.
    viewer_seat: int | None = None


@dataclass(frozen=True)
class LoadedMatchTurn(Generic[StateT, ActionT]):
    """Typed turn data rehydrated from a match transcript."""

    seat: Seat | None
    action: ActionT | None
    event_payloads: tuple[JSONMapping, ...]
    result: RuleResult | None
    result_payload: JSONMapping | None
    post_state: StateT
    post_snapshot: SnapshotEnvelope
    kind: str = TURN_KIND_ACTION
    outcome: object = None
    actions: dict[Seat, ActionT] | None = None


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
                action=(
                    match.definition.serializer.dump_action(turn.action)
                    if turn.action is not None
                    else None
                ),
                kind=turn.kind,
                outcome=(
                    dump_chance_outcome(match.definition.serializer, turn.outcome)
                    if turn.kind == TURN_KIND_CHANCE
                    else None
                ),
                actions=_dump_joint_actions(match.definition.serializer, turn.actions),
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
    _ensure_turn_shapes(transcript_payload)
    if transcript_payload.view != VIEW_FULL:
        raise ValueError(
            f"A {transcript_payload.view!r}-view transcript cannot be loaded or replayed: "
            f"it omits hidden information. Only a full transcript can."
        )

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
            kind=turn_payload.kind,
            outcome=(
                load_chance_outcome(definition.serializer, turn_payload.outcome)
                if turn_payload.outcome is not None
                else None
            ),
            action=(
                cast(ActionT, definition.serializer.load_action(turn_payload.action))
                if turn_payload.action is not None
                else None
            ),
            actions=(
                {
                    int(seat): cast(ActionT, definition.serializer.load_action(action))
                    for seat, action in turn_payload.actions.items()
                }
                if turn_payload.actions is not None
                else None
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


def _ensure_turn_shapes(payload: MatchTranscriptPayload) -> None:
    """Reject a transcript whose shape no build of this code could have written.

    Checked before replay so a forged field cannot ride along unexamined: replay
    only ever reads the fields that belong to a turn's kind.
    """

    if payload.schema_version not in SUPPORTED_MATCH_TRANSCRIPT_SCHEMA_VERSIONS:
        raise ValueError(
            f"Transcript schema_version {payload.schema_version!r} is not one of "
            f"{SUPPORTED_MATCH_TRANSCRIPT_SCHEMA_VERSIONS}."
        )
    if payload.schema_version < 3 and payload.view != VIEW_FULL:
        raise ValueError("Transcripts before schema_version 3 have no views.")
    if payload.view == VIEW_SEAT and payload.viewer_seat is None:
        raise ValueError("A seat-view transcript must name its viewer_seat.")
    if payload.view != VIEW_SEAT and payload.viewer_seat is not None:
        raise ValueError("Only a seat-view transcript has a viewer_seat.")

    for index, turn in enumerate(payload.turns, start=1):
        for event in turn.events:
            marked = {"is_public", "audience"} & event.model_fields_set
            if marked and payload.schema_version < 3:
                raise ValueError(f"Turn {index}: event audiences predate schema_version 3.")
            if event.is_public and event.audience is not None:
                raise ValueError(f"Turn {index}: a public event has no audience.")
            if not event.is_public and not event.audience:
                raise ValueError(f"Turn {index}: a private event must name its audience.")
        if turn.kind == TURN_KIND_CHANCE:
            if payload.schema_version < 2:
                raise ValueError(
                    f"Turn {index}: a schema_version 1 transcript predates chance turns."
                )
            if turn.seat is not None or turn.action is not None:
                raise ValueError(f"Turn {index}: a chance turn has no seat and no action.")
            if turn.outcome is None:
                raise ValueError(f"Turn {index}: a chance turn must carry its outcome.")
        elif turn.kind == TURN_KIND_ACTION:
            if turn.seat is None or turn.action is None:
                raise ValueError(f"Turn {index}: an action turn needs a seat and an action.")
            if turn.outcome is not None:
                raise ValueError(f"Turn {index}: an action turn has no chance outcome.")
        elif turn.kind == TURN_KIND_JOINT:
            if payload.schema_version < 4:
                raise ValueError(
                    f"Turn {index}: transcripts before schema_version 4 have no joint turns."
                )
            if turn.seat is not None or turn.action is not None or turn.outcome is not None:
                raise ValueError(
                    f"Turn {index}: a joint turn has no single seat, action, or outcome."
                )
            keys = list((turn.actions or {}).keys())
            if len(keys) < 2 or keys != sorted(keys, key=_seat_key) or any(
                _seat_key(key) < 0 for key in keys
            ):
                raise ValueError(
                    f"Turn {index}: a joint turn maps two or more seats, in order, to actions."
                )
        else:
            raise ValueError(f"Turn {index}: unknown turn kind {turn.kind!r}.")
        if turn.kind != TURN_KIND_JOINT and turn.actions is not None:
            raise ValueError(f"Turn {index}: only a joint turn carries actions.")


def _seat_key(key: str) -> int:
    """A joint turn's seat key as an int; -1 for anything but a canonical one."""

    return int(key) if key.isdigit() and str(int(key)) == key else -1


def _dump_joint_actions(serializer: Any, actions: Any) -> dict[str, JSONMapping] | None:
    if actions is None:
        return None
    return {str(seat): serializer.dump_action(actions[seat]) for seat in sorted(actions)}


def validate_match_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
) -> LoadedMatchTranscript[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Validate a transcript by replaying it against a fresh local match.

    Every failure is a ``ValueError``; a rules-engine rejection during replay (an
    illegal recorded action, an impossible recorded outcome) is chained as its
    cause.
    """

    return _replay_match_transcript(definition, payload)[0]


def _replay_match_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
) -> tuple[
    LoadedMatchTranscript[ConfigT, StateT, ActionT, ObservationT, ResultT],
    LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
]:
    """Validate ``payload`` by replay; return it loaded, with the replayed match."""

    try:
        return _validate_match_transcript(definition, payload)
    except ArenaCoreError as exc:
        raise ValueError(f"Transcript validation failed: {exc.message}") from exc
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        # A structurally malformed payload a model did not catch (a Win result
        # without a seat, a state a loader indexes into): still a bad transcript,
        # and callers rely on getting a ValueError for one.
        raise ValueError(
            f"Transcript validation failed: malformed payload ({type(exc).__name__})."
        ) from exc


def _validate_match_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
) -> tuple[
    LoadedMatchTranscript[ConfigT, StateT, ActionT, ObservationT, ResultT],
    LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
]:
    loaded_transcript = load_match_transcript(definition, payload)
    # A replay match never samples: it waits at each chance node for the
    # recorded outcome. Validation therefore needs no seed.
    replay_match = start_replay_match(definition, loaded_transcript.config)

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

    # Replay never re-rolls: a chance turn applies its recorded outcome, which
    # the engine revalidates just as it revalidates a recorded action. The full
    # comparison below then proves every post-state, snapshot, and event matches.
    for loaded_turn in loaded_transcript.turns:
        if loaded_turn.kind == TURN_KIND_CHANCE:
            if loaded_turn.outcome is None:
                raise ValueError(
                    "Transcript validation failed: a chance turn must carry its outcome."
                )
            replay_match = apply_match_chance(replay_match, loaded_turn.outcome)
            continue
        if loaded_turn.kind == TURN_KIND_JOINT:
            if not loaded_turn.actions:
                raise ValueError(
                    "Transcript validation failed: a joint turn must carry its actions."
                )
            replay_match = apply_match_joint_action(replay_match, loaded_turn.actions)
            continue
        if loaded_turn.kind != TURN_KIND_ACTION:
            raise ValueError(
                f"Transcript validation failed: unknown turn kind {loaded_turn.kind!r}."
            )
        if loaded_turn.seat is None or loaded_turn.action is None:
            raise ValueError(
                "Transcript validation failed: an action turn must carry both a seat "
                f"and an action (turn kind {loaded_turn.kind!r})."
            )
        replay_match = apply_match_action(replay_match, loaded_turn.seat, loaded_turn.action)

    if is_chance_node(replay_match.rules_engine, replay_match.state):
        raise ValueError(
            "Transcript validation failed: it ends at a pending chance node, which a "
            "live match never does; a chance turn is missing."
        )

    if len(replay_match.turns) != len(loaded_transcript.turns):
        raise ValueError(
            "Transcript validation failed: replay produced "
            f"{len(replay_match.turns)} turn(s) but the transcript records "
            f"{len(loaded_transcript.turns)}."
        )

    for turn_index, (loaded_turn, generated_turn) in enumerate(
        zip(loaded_transcript.turns, replay_match.turns), start=1
    ):
        if loaded_turn.kind != generated_turn.kind:
            raise ValueError(
                f"Transcript validation failed: turn {turn_index} is recorded as "
                f"{loaded_turn.kind!r} but replayed as {generated_turn.kind!r}."
            )

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

    return loaded_transcript, replay_match


def dump_domain_event(event: DomainEvent) -> MatchEventPayload:
    """Serialize one domain event to its JSON-safe payload.

    Public because the server puts events on the wire: since Phase 37 a chance
    outcome is carried by its events and cannot be recomputed by a client.
    """

    payload = _dump_dataclass_fields(event)
    return MatchEventPayload(
        event_type=event.event_type,
        payload=payload,
        is_public=event.is_public,
        audience=event.audience(),
    )


# ---------------------------------------------------------------------------
# Per-viewer transcripts (Phase 38)
# ---------------------------------------------------------------------------


def transcript_view_for(
    definition: GameDefinition[Any, Any, Any, Any, Any], viewer: Viewer
) -> tuple[TranscriptView, int | None]:
    """The ``(view, viewer_seat)`` a viewer's transcript carries.

    A perfect-information game has nothing to redact, so every viewer gets the
    full transcript, labelled as such: it stays replayable, and its payloads are
    exactly what they were before views existed.
    """

    check_viewer(viewer)
    if not definition.has_hidden_information:
        return VIEW_FULL, None
    if viewer is None:
        return VIEW_PUBLIC, None
    return VIEW_SEAT, viewer


def filter_event_payloads(
    event_payloads: Sequence[JSONMapping], viewer: Viewer
) -> list[JSONMapping]:
    """Drop serialized events ``viewer`` may not see."""

    return [p for p in event_payloads if event_payload_visible_to(p, viewer)]


def turn_payload_for_viewer(
    definition: GameDefinition[Any, Any, Any, Any, Any],
    config: Any,
    *,
    kind: str,
    seat: int | None,
    action: JSONMapping | None,
    outcome: Any,
    event_payloads: Sequence[JSONMapping],
    result: JSONMapping | None,
    post_state: Any,
    viewer: Viewer,
    actions: dict[str, JSONMapping] | None = None,
) -> MatchTurnPayload:
    """One turn as ``viewer`` may see it.

    Actions and results are public: a move is announced to the table, and a
    joint turn's actions are revealed together, once every seat has chosen.
    Snapshots, chance outcomes, and events are redacted per viewer.
    """

    serializer = definition.serializer
    return MatchTurnPayload(
        seat=seat,
        action=action,
        actions=actions,
        kind=kind,
        outcome=(
            dump_chance_outcome_for_viewer(serializer, outcome, viewer)
            if kind == TURN_KIND_CHANCE
            else None
        ),
        events=[
            MatchEventPayload.model_validate(p)
            for p in filter_event_payloads(event_payloads, viewer)
        ],
        result=MatchResultPayload.model_validate(result) if result is not None else None,
        post_snapshot=build_snapshot_for_viewer(definition, config, post_state, viewer),
    )


def _turn_record_for_viewer(
    definition: GameDefinition[Any, Any, Any, Any, Any],
    config: Any,
    turn: Any,
    viewer: Viewer,
) -> MatchTurnPayload:
    return turn_payload_for_viewer(
        definition,
        config,
        kind=turn.kind,
        seat=turn.seat,
        action=(
            definition.serializer.dump_action(turn.action) if turn.action is not None else None
        ),
        outcome=turn.outcome,
        actions=_dump_joint_actions(definition.serializer, turn.actions),
        event_payloads=[dump_domain_event(event).model_dump(mode="json") for event in turn.events],
        result=(
            _dump_rule_result(turn.result).model_dump(mode="json")
            if turn.result is not None
            else None
        ),
        post_state=turn.post_state,
        viewer=viewer,
    )


def turn_record_for_viewer(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    turn_index: int,
    viewer: Viewer,
) -> MatchTurnPayload:
    """Turn ``turn_index`` of a live match as ``viewer`` may see it.

    What the server puts in ``turn_committed`` for each recipient.
    """

    return _turn_record_for_viewer(
        match.definition, match.config, match.turns[turn_index], viewer
    )


def dump_match_transcript_for_viewer(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    viewer: Viewer,
) -> JSONMapping:
    """The transcript ``viewer`` may receive: a seat's, or the public's (``None``).

    The full transcript for a perfect-information game.
    """

    definition = match.definition
    view, viewer_seat = transcript_view_for(definition, viewer)
    if view == VIEW_FULL:
        return dump_match_transcript(match)

    serializer = definition.serializer
    payload = MatchTranscriptPayload(
        game_id=definition.game_id,
        schema_version=MATCH_TRANSCRIPT_SCHEMA_VERSION,
        config=dump_config_for_viewer(serializer, match.config, viewer),
        initial_snapshot=build_snapshot_for_viewer(
            definition, match.config, match.rules_engine.initial_state(match.config), viewer
        ),
        turns=[
            _turn_record_for_viewer(definition, match.config, turn, viewer)
            for turn in match.turns
        ],
        view=view,
        viewer_seat=viewer_seat,
    )
    return payload.model_dump(mode="json")


def redact_match_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
    viewer: Viewer,
) -> JSONMapping:
    """Produce ``viewer``'s transcript from a saved **full** transcript.

    What a replay viewer uses to show one seat's perspective of an archived
    match. For a perfect-information game the payload comes back unredacted.

    The file is replayed first, and the view is built from the *replayed*
    match: what a viewer may see is decided by the game, never by the
    ``is_public`` / ``audience`` markers in the file. Trusting them let a file
    with the markers stripped show every hand. Raises ``ValueError`` for any
    transcript that does not replay.
    """

    check_viewer(viewer)
    _, replay_match = _replay_match_transcript(definition, payload)
    view, _ = transcript_view_for(definition, viewer)
    if view == VIEW_FULL:
        return MatchTranscriptPayload.model_validate(payload).model_dump(mode="json")
    return dump_match_transcript_for_viewer(replay_match, viewer)


#: Retained for internal callers predating the public name.
_dump_domain_event = dump_domain_event


def dump_rule_result(result: RuleResult | None) -> JSONMapping | None:
    """A rule result as JSON: ``{"result_type": "Win", "payload": {"seat": 0}}``.

    The shape a transcript turn's ``result`` has; the server sends the same in
    ``match_finished.result`` and ``match_state.result``.
    """

    payload = _dump_rule_result(result)
    return None if payload is None else payload.model_dump(mode="json")


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
        seat = result_payload.payload.get("seat")
        if type(seat) is not int:
            raise ValueError("A Win result must name the winning seat.")
        return Win(seat=seat)
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
    "dump_domain_event",
    "MatchEventPayload",
    "MatchResultPayload",
    "MatchTranscriptPayload",
    "MatchTurnPayload",
    "SUPPORTED_MATCH_TRANSCRIPT_SCHEMA_VERSIONS",
    "TranscriptView",
    "VIEW_FULL",
    "VIEW_PUBLIC",
    "VIEW_SEAT",
    "dump_match_transcript",
    "dump_match_transcript_for_viewer",
    "filter_event_payloads",
    "load_match_transcript",
    "redact_match_transcript",
    "transcript_view_for",
    "turn_payload_for_viewer",
    "turn_record_for_viewer",
    "validate_match_transcript",
]
