"""JSON-safe runtime envelopes for transcripts, CLI output, and future UI use."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields, is_dataclass
from typing import Any, Final, Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.public_view import (
    FULL_VIEW,
    VIEWER_SEATS,
    FullView,
    Viewer,
    check_viewer,
)
from arena.core.results import RuleResult
from arena.core.serializer import JSONMapping, SnapshotEnvelope
from arena.core.simultaneous import acting_seats
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
    AbortReason,
    MatchAborted,
    MatchCreated,
    MatchFinished,
    MatchStarted,
    PlayerRecord,
    PolicyDecided,
    PolicyRetried,
    RuntimeEvent,
    RuntimeLifecycle,
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
RUNTIME_STATUS_SCHEMA_VERSION: Final = 4

#: Versions the status validator accepts.
SUPPORTED_RUNTIME_STATUS_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4)
# Bumped to 2 in Phase 37: the embedded match transcript's turns gained a
# `kind`, and a chance turn carries no seat and no action.
# Bumped to 3 in Phase 38: payloads declare their `view` (full, one seat's, or
# the public's), and a redacted one omits hidden information.
# Bumped to 4 in Phase 41: the embedded match transcript can carry joint turns
# (several seats acting at once), with an `actions` map and no single seat.
RUNTIME_TRANSCRIPT_SCHEMA_VERSION: Final = 4

#: Versions the transcript validator accepts. v1 predates chance nodes; v1 and
#: v2 predate views and are always full.
SUPPORTED_RUNTIME_TRANSCRIPT_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4)

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


#: Lifecycle values an envelope may carry. Checked by a validator rather than
#: typed as a Literal: the field's JSON Schema is published at
#: /schemas/payloads, which must stay byte-stable within a wire version.
_LIFECYCLES = frozenset(lifecycle.value for lifecycle in RuntimeLifecycle)


def _check_envelope(
    *,
    lifecycle: str,
    abort: RuntimeAbortPayload | None,
    players: list[RuntimePlayerPayload],
    view: str,
    viewer_seat: int | None,
) -> None:
    """What every status and transcript envelope must agree with itself on."""

    if lifecycle not in _LIFECYCLES:
        raise ValueError(f"unknown lifecycle {lifecycle!r}")
    if (lifecycle == RuntimeLifecycle.ABORTED.value) != (abort is not None):
        raise ValueError("abort is present exactly when the lifecycle is 'aborted'")
    seats = [player.seat for player in players]
    ids = [player.player_id for player in players]
    if len(set(seats)) != len(seats) or len(set(ids)) != len(ids):
        raise ValueError("players must have distinct seats and ids")
    if view == VIEW_SEAT:
        if viewer_seat not in VIEWER_SEATS:
            raise ValueError("a seat view names the seat it was built for")
    elif viewer_seat is not None:
        raise ValueError(f"a {view!r} view has no viewer_seat")
    if view != VIEW_FULL and abort is not None and abort.cause_message is not None:
        # The text of an exception can carry anything, an agent's reasoning
        # about its own hand included: only the full view keeps it.
        raise ValueError(f"a {view!r} view carries no abort cause_message")


class RuntimeSessionStatusPayload(BaseModel):
    """JSON-safe session status envelope for CLI and UI consumers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1, 2, 3, 4]
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

    @model_validator(mode="after")
    def _consistent(self) -> "RuntimeSessionStatusPayload":
        _check_envelope(
            lifecycle=self.lifecycle,
            abort=self.abort,
            players=self.players,
            view=self.view,
            viewer_seat=self.viewer_seat,
        )
        return self


class RuntimeTranscriptPayload(BaseModel):
    """JSON-safe runtime transcript envelope around a local match transcript."""

    model_config = ConfigDict(extra="forbid", strict=True)

    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    # Accepts every version this build reads; older ones stay readable.
    schema_version: Literal[1, 2, 3, 4]
    lifecycle: str = Field(min_length=1)
    players: list[RuntimePlayerPayload]
    events: list[RuntimeEventPayload]
    abort: RuntimeAbortPayload | None
    match_transcript: JSONMapping | None
    #: Phase 38: whose view this is; mirrors ``match_transcript.view``.
    view: TranscriptView = VIEW_FULL
    viewer_seat: int | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "RuntimeTranscriptPayload":
        _check_envelope(
            lifecycle=self.lifecycle,
            abort=self.abort,
            players=self.players,
            view=self.view,
            viewer_seat=self.viewer_seat,
        )
        inner = self.match_transcript
        # An empty mapping is the server's placeholder (see
        # runtime_bridge._build_transcript_payload); it is never a transcript.
        if inner:
            # Transcripts older than views (v1, v2) carry none and are full.
            inner_view = inner.get("view", VIEW_FULL)
            inner_seat = inner.get("viewer_seat")
            if (inner_view, inner_seat) != (self.view, self.viewer_seat):
                raise ValueError(
                    "the envelope's view must be its match transcript's view: "
                    f"{(self.view, self.viewer_seat)!r} wraps {(inner_view, inner_seat)!r}"
                )
        return self


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
            seats = acting_seats(local_match.rules_engine, local_match.state)
            # Several seats acting at once (Phase 41) have no single current seat.
            current_seat = seats[0] if len(seats) == 1 else None
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
        abort=_dump_abort(session.abort, view),
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
            _dump_runtime_event(event, view)
            for event in session.events
            if _runtime_event_visible(event, view, viewer)
        ],
        abort=_dump_abort(session.abort, view),
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
                _redact_runtime_event_payload(event, view)
                for event in runtime_payload.events
                if _runtime_event_payload_visible(event, view, viewer)
            ],
            "abort": (
                runtime_payload.abort
                if view == VIEW_FULL
                else _redact_abort_payload(runtime_payload.abort)
            ),
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
            cast(Any, serializer.load_config(latest.config)),
            cast(Any, serializer.load_state(latest.state)),
            viewer,
        )
    redacted = status.model_copy(
        update={
            "schema_version": RUNTIME_STATUS_SCHEMA_VERSION,
            "latest_snapshot": latest,
            "abort": status.abort if view == VIEW_FULL else _redact_abort_payload(status.abort),
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


def _redact_runtime_event_payload(
    event: RuntimeEventPayload, view: TranscriptView
) -> RuntimeEventPayload:
    abort = event.payload.get("abort")
    if view == VIEW_FULL or event.event_type != "MatchAborted" or not isinstance(abort, dict):
        return event
    return event.model_copy(
        update={"payload": {**event.payload, "abort": {**abort, "cause_message": None}}}
    )


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
    abort = runtime_payload.abort
    if abort is not None and abort.reason not in _ABORT_REASONS:
        raise ValueError(f"Unknown abort reason {abort.reason!r}.")
    if runtime_payload.match_transcript is None:
        return None
    loaded = validate_match_transcript(definition, runtime_payload.match_transcript)
    final_state = loaded.turns[-1].post_state if loaded.turns else loaded.initial_state
    finished = runtime_payload.lifecycle == RuntimeLifecycle.FINISHED.value
    if finished != definition.rules_engine.is_terminal(final_state):
        raise ValueError(
            f"A {runtime_payload.lifecycle!r} transcript must "
            f"{'' if finished else 'not '}end at a finished game."
        )
    return loaded


#: Abort reasons this build knows. The wire model keeps ``reason`` a free string,
#: so a newer server's reason does not break an older client; a saved
#: transcript is held to the known set.
_ABORT_REASONS = frozenset(reason.value for reason in AbortReason)


def _dump_player(player: PlayerRecord) -> RuntimePlayerPayload:
    return RuntimePlayerPayload(
        player_id=player.player_id,
        seat=player.seat,
        label=player.label,
    )


def _dump_abort(
    abort: AbortMetadata | None, view: TranscriptView = VIEW_FULL
) -> RuntimeAbortPayload | None:
    if abort is None:
        return None
    return RuntimeAbortPayload(
        reason=abort.reason.value,
        message=abort.message,
        cause_type=abort.cause_type,
        cause_message=abort.cause_message if view == VIEW_FULL else None,
    )


def _redact_abort_payload(abort: RuntimeAbortPayload | None) -> RuntimeAbortPayload | None:
    """An abort as a non-full view carries it: without the cause's text.

    ``cause_message`` is ``str(exception)``, which can hold anything. An Ollama
    seat that runs out of retries puts the model's raw reply there, thoughts
    about its own hand included.
    """

    if abort is None or abort.cause_message is None:
        return abort
    return abort.model_copy(update={"cause_message": None})


def _dump_runtime_event(
    event: RuntimeEvent, view: TranscriptView = VIEW_FULL
) -> RuntimeEventPayload:
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
        abort = _dump_abort(event.abort, view)
        assert abort is not None  # a MatchAborted event always carries its abort
        payload = {"abort": abort.model_dump(mode="json")}
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
