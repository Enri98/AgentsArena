"""JSON-safe runtime envelopes for transcripts, CLI output, and future UI use."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields, is_dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.public_view import FULL_VIEW, FullView, Viewer, check_viewer
from arena.core.results import RuleResult
from arena.core.serializer import JSONMapping, SnapshotEnvelope
from arena.match.local_match import build_snapshot_for_viewer
from arena.match.transcript import (
    VIEW_FULL,
    VIEW_SEAT,
    LoadedMatchTranscript,
    TranscriptView,
    dump_match_transcript,
    dump_match_transcript_for_viewer,
    redact_match_transcript,
    transcript_view_for,
    validate_match_transcript,
)
from arena.runtime.models import (
    AbortMetadata,
    MatchAborted,
    MatchCreated,
    MatchFinished,
    MatchStarted,
    PlayerRecord,
    PolicyDecided,
    PolicyRetried,
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

# Moves with RUNTIME_TRANSCRIPT_SCHEMA_VERSION: arena.ui cross-checks that a
# status and a transcript come from the same runtime payload generation.
RUNTIME_STATUS_SCHEMA_VERSION = 3

#: Versions the status validator accepts.
SUPPORTED_RUNTIME_STATUS_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3)
# Bumped to 2 in Phase 37: the embedded match transcript's turns gained a
# `kind`, and a chance turn carries no seat and no action.
# Bumped to 3 in Phase 38: payloads declare their `view` (full, one seat's, or
# the public's), and a redacted one omits hidden information.
RUNTIME_TRANSCRIPT_SCHEMA_VERSION = 3

#: Versions the transcript validator accepts. v1 predates chance nodes; v1 and
#: v2 predate views and are always full.
SUPPORTED_RUNTIME_TRANSCRIPT_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3)

#: Runtime events that carry an agent's own reasoning. In a hidden-information
#: game a "thought" can reveal a hand, so a viewer sees only its own seat's.
_SEAT_PRIVATE_RUNTIME_EVENTS = (PolicyDecided, PolicyRetried)


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

    event_scope: Literal["runtime"]
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

    schema_version: Literal[1, 2, 3]
    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    lifecycle: str = Field(min_length=1)
    players: list[RuntimePlayerPayload]
    current_seat: int | None
    turn_count: int
    result: RuntimeResultPayload | None
    latest_snapshot: SnapshotEnvelope | None
    abort: RuntimeAbortPayload | None
    #: Phase 38: whose view ``latest_snapshot`` is. See ``TranscriptView``.
    view: TranscriptView = VIEW_FULL
    viewer_seat: int | None = None


class RuntimeTranscriptPayload(BaseModel):
    """JSON-safe runtime transcript envelope around a local match transcript."""

    model_config = ConfigDict(extra="forbid", strict=True)

    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    # Accepts every version this build reads; older ones stay readable.
    schema_version: Literal[1, 2, 3]
    lifecycle: str = Field(min_length=1)
    players: list[RuntimePlayerPayload]
    events: list[RuntimeEventPayload]
    abort: RuntimeAbortPayload | None
    match_transcript: JSONMapping | None
    #: Phase 38: whose view this is; mirrors ``match_transcript.view``.
    view: TranscriptView = VIEW_FULL
    viewer_seat: int | None = None


def dump_session_status(
    session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    *,
    viewer: Viewer | FullView = FULL_VIEW,
) -> JSONMapping:
    """Dump the current runtime session status as a JSON-safe mapping.

    ``viewer`` (Phase 38) redacts ``latest_snapshot`` to a seat's view, or the
    public's for ``None``. The default is the full, unredacted status.
    """

    local_match = session.local_match
    current_seat = None
    latest_snapshot = None
    result = None
    turn_count = 0
    view, viewer_seat = _view_of(session.definition, viewer)

    if local_match is not None:
        turn_count = len(local_match.turns)
        latest_snapshot = (
            local_match.turns[-1].post_snapshot
            if local_match.turns
            else local_match.initial_snapshot
        )
        if not isinstance(viewer, FullView):
            latest_snapshot = build_snapshot_for_viewer(
                local_match.definition, local_match.config, local_match.state, viewer
            )
        if not local_match.rules_engine.is_terminal(local_match.state):
            current_seat = local_match.rules_engine.current_seat(local_match.state)
        result = _dump_rule_result(local_match.rules_engine.result(local_match.state))

    payload = RuntimeSessionStatusPayload(
        schema_version=RUNTIME_STATUS_SCHEMA_VERSION,
        match_id=session.match_id,
        game_id=session.definition.game_id,
        lifecycle=session.lifecycle.value,
        players=[_dump_player(player) for player in session.players],
        current_seat=current_seat,
        turn_count=turn_count,
        result=result,
        latest_snapshot=latest_snapshot,
        abort=_dump_abort(session.abort),
        view=view,
        viewer_seat=viewer_seat,
    )
    return payload.model_dump(mode="json")


def dump_runtime_transcript(
    session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    *,
    viewer: Viewer | FullView = FULL_VIEW,
    match_transcript: JSONMapping | None = None,
) -> JSONMapping:
    """Dump a runtime transcript envelope without validating replay.

    ``viewer`` (Phase 38) selects a seat's transcript, or the public's for
    ``None``. The default is the full transcript, which only the server should
    hold for a hidden-information game. A perfect-information game's transcript
    is full for every viewer.

    ``match_transcript`` lets a caller that builds the viewer's match transcript
    incrementally (the server, which must not rebuild a long one per attach)
    supply it. It must be exactly what this function would compute.
    """

    view, viewer_seat = _view_of(session.definition, viewer)
    local_match = session.local_match
    if local_match is not None and match_transcript is None:
        match_transcript = (
            dump_match_transcript(local_match)
            if view == VIEW_FULL
            else dump_match_transcript_for_viewer(local_match, viewer)  # type: ignore[arg-type]
        )

    payload = RuntimeTranscriptPayload(
        match_id=session.match_id,
        game_id=session.definition.game_id,
        schema_version=RUNTIME_TRANSCRIPT_SCHEMA_VERSION,
        lifecycle=session.lifecycle.value,
        players=[_dump_player(player) for player in session.players],
        events=[
            _dump_runtime_event(event)
            for event in session.events
            if _runtime_event_visible(event, view, viewer)
        ],
        abort=_dump_abort(session.abort),
        match_transcript=match_transcript,
        view=view,
        viewer_seat=viewer_seat,
    )
    return payload.model_dump(mode="json")


def _view_of(definition: object, viewer: Viewer | FullView) -> tuple[TranscriptView, int | None]:
    if isinstance(viewer, FullView):
        return VIEW_FULL, None
    return transcript_view_for(definition, viewer)  # type: ignore[arg-type]


def _runtime_event_visible(
    event: RuntimeEvent, view: TranscriptView, viewer: Viewer | FullView
) -> bool:
    if view == VIEW_FULL or not isinstance(event, _SEAT_PRIVATE_RUNTIME_EVENTS):
        return True
    return view == VIEW_SEAT and event.seat == viewer


def redact_runtime_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
    viewer: Viewer,
) -> JSONMapping:
    """``viewer``'s transcript from a saved **full** runtime transcript (Phase 38).

    For replaying one seat's perspective of an archived match. The input must be
    full: a redacted transcript cannot be re-redacted for someone else.
    """

    check_viewer(viewer)
    runtime_payload = RuntimeTranscriptPayload.model_validate(payload)
    if runtime_payload.view != VIEW_FULL:
        raise ValueError(
            f"Only a full transcript can be redacted; this one is a "
            f"{runtime_payload.view!r} view."
        )
    view, viewer_seat = transcript_view_for(definition, viewer)
    match_transcript = runtime_payload.match_transcript
    if match_transcript is not None:
        match_transcript = redact_match_transcript(definition, match_transcript, viewer)
    redacted = runtime_payload.model_copy(
        update={
            "schema_version": RUNTIME_TRANSCRIPT_SCHEMA_VERSION,
            "match_transcript": match_transcript,
            "events": [
                event
                for event in runtime_payload.events
                if _runtime_event_payload_visible(event, view, viewer)
            ],
            "view": view,
            "viewer_seat": viewer_seat,
        }
    )
    return redacted.model_dump(mode="json")


def redact_session_status(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
    viewer: Viewer,
) -> JSONMapping:
    """``viewer``'s status from a saved **full** status payload (Phase 38)."""

    check_viewer(viewer)
    status = validate_session_status(payload)
    if status.view != VIEW_FULL:
        raise ValueError(
            f"Only a full status can be redacted; this one is a {status.view!r} view."
        )
    view, viewer_seat = transcript_view_for(definition, viewer)
    latest = status.latest_snapshot
    if latest is not None and view != VIEW_FULL:
        serializer = definition.serializer
        latest = build_snapshot_for_viewer(
            definition,
            serializer.load_config(latest.config),
            serializer.load_state(latest.state),
            viewer,
        )
    redacted = status.model_copy(
        update={
            "schema_version": RUNTIME_STATUS_SCHEMA_VERSION,
            "latest_snapshot": latest,
            "view": view,
            "viewer_seat": viewer_seat,
        }
    )
    return redacted.model_dump(mode="json")


def _runtime_event_payload_visible(
    event: RuntimeEventPayload, view: TranscriptView, viewer: Viewer
) -> bool:
    if view == VIEW_FULL or event.event_type not in ("PolicyDecided", "PolicyRetried"):
        return True
    return view == VIEW_SEAT and event.payload.get("seat") == viewer


def validate_session_status(payload: JSONMapping) -> RuntimeSessionStatusPayload:
    """Validate a dumped session status payload against the stable runtime contract."""

    _ensure_supported_schema_version(
        payload=payload,
        expected=RUNTIME_STATUS_SCHEMA_VERSION,
        supported=SUPPORTED_RUNTIME_STATUS_SCHEMA_VERSIONS,
        context="Runtime session status",
    )
    status_payload = RuntimeSessionStatusPayload.model_validate(payload)
    return status_payload


def validate_runtime_transcript(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    payload: JSONMapping,
) -> LoadedMatchTranscript[ConfigT, StateT, ActionT, ObservationT, ResultT] | None:
    """Validate the wrapped local match transcript when one is present."""

    _ensure_supported_schema_version(
        payload=payload,
        expected=RUNTIME_TRANSCRIPT_SCHEMA_VERSION,
        supported=SUPPORTED_RUNTIME_TRANSCRIPT_SCHEMA_VERSIONS,
        context="Runtime transcript",
    )
    runtime_payload = RuntimeTranscriptPayload.model_validate(payload)
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
    elif isinstance(event, PolicyRetried):
        payload = {
            "seat": event.seat,
            "attempt": event.attempt,
            "reason_summary": event.reason_summary,
        }
    elif isinstance(event, PolicyDecided):
        payload = {
            "seat": event.seat,
            "attempt": event.attempt,
            "thought": event.thought,
        }
    else:
        payload = {}

    return RuntimeEventPayload(
        event_scope="runtime",
        event_type=event.event_type,
        payload=payload,
    )


def _ensure_supported_schema_version(
    *,
    payload: JSONMapping,
    expected: int,
    context: str,
    supported: tuple[int, ...] | None = None,
) -> None:
    """Reject a payload this build cannot read.

    ``supported`` lets a payload type accept more than the version it emits —
    a v1 transcript predates chance nodes and is still perfectly readable.
    """

    accepted = supported if supported is not None else (expected,)
    actual = payload.get("schema_version")
    if actual is None:
        return
    if actual not in accepted:
        expected_text = (
            repr(expected)
            if len(accepted) == 1
            else " or ".join(repr(v) for v in accepted)
        )
        raise ValueError(
            f"{context} schema_version {actual!r} does not match {expected_text}."
        )


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
    "RUNTIME_STATUS_SCHEMA_VERSION",
    "SUPPORTED_RUNTIME_STATUS_SCHEMA_VERSIONS",
    "RUNTIME_TRANSCRIPT_SCHEMA_VERSION",
    "SUPPORTED_RUNTIME_TRANSCRIPT_SCHEMA_VERSIONS",
    "RuntimeAbortPayload",
    "RuntimeEventPayload",
    "RuntimePlayerPayload",
    "RuntimeResultPayload",
    "RuntimeSessionStatusPayload",
    "RuntimeTranscriptPayload",
    "dump_runtime_transcript",
    "dump_session_status",
    "redact_runtime_transcript",
    "redact_session_status",
    "validate_session_status",
    "validate_runtime_transcript",
]
