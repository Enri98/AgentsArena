"""Deterministic screen-level payloads derived from runtime envelopes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_serializer

from arena.runtime import (
    RuntimeAbortPayload,
    RuntimePlayerPayload,
    RuntimeResultPayload,
    RuntimeTranscriptPayload,
    validate_session_status,
)

JSONMapping: TypeAlias = dict[str, JsonValue]

UI_ADAPTER_SCHEMA_VERSION = 1


class UIScreenPlayerPayload(BaseModel):
    """Player identity and seat data for screen-level consumers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    player_id: str = Field(min_length=1)
    seat: int = Field(ge=0)
    label: str | None = None


class UIScreenAbortPayload(BaseModel):
    """Runtime abort details preserved for screen-level consumers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str = Field(min_length=1)
    message: str = Field(min_length=1)
    cause_type: str | None = None
    cause_message: str | None = None


class UIScreenResultPayload(BaseModel):
    """Current or turn-level result data for screen-level consumers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    result_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class UIScreenRuntimeEventPayload(BaseModel):
    """Runtime event data kept separate from game-domain turn events."""

    model_config = ConfigDict(extra="forbid", strict=True)

    event_scope: Literal["runtime"]
    event_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class UIScreenTurnPayload(BaseModel):
    """Accepted game turn data for transcript/history screens.

    A chance turn (Phase 37) has no seat and no action; it carries the recorded
    `outcome` instead, and `kind` tells the two apart.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    turn_index: int = Field(ge=1)
    kind: str = "action"
    seat: int | None = Field(default=None, ge=0)
    action: JSONMapping | None = None
    outcome: JSONMapping | None = None
    events: list[JSONMapping]
    result: UIScreenResultPayload | None
    post_snapshot: JSONMapping
    state_payload: JSONMapping


class _SnapshotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    game_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    config: JSONMapping
    state: JSONMapping


class _MatchEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)
    is_public: bool = True
    audience: list[int] | None = None

    @model_serializer(mode="wrap")
    def _omit_public_marker(self, handler: Any) -> Any:
        # Mirrors arena.match.MatchEventPayload: public events keep their
        # pre-Phase-38 shape.
        data = handler(self)
        if self.is_public:
            data.pop("is_public", None)
            data.pop("audience", None)
        return data


class _MatchResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    result_type: str = Field(min_length=1)
    payload: JSONMapping = Field(default_factory=dict)


class _MatchTurnPayload(BaseModel):
    """Mirrors arena.match.MatchTurnPayload for validation at the UI boundary.

    Phase 37: a chance turn has no seat and no action, so both are optional and
    `kind` distinguishes them; it carries the recorded `outcome` instead.
    Defaults keep a v1 transcript valid.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int | None = Field(default=None, ge=0)
    action: JSONMapping | None = None
    events: list[_MatchEventPayload]
    result: _MatchResultPayload | None
    post_snapshot: _SnapshotPayload
    kind: str = "action"
    outcome: JSONMapping | None = None


class _MatchTranscriptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    game_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    config: JSONMapping
    initial_snapshot: _SnapshotPayload
    turns: list[_MatchTurnPayload]
    view: Literal["full", "seat", "public"] = "full"
    viewer_seat: int | None = None


class UIMatchStatusPayload(BaseModel):
    """Current match status shaped for UI consumers without rendering logic."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    runtime_schema_version: int = Field(ge=1)
    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    lifecycle: str = Field(min_length=1)
    players: list[UIScreenPlayerPayload]
    current_seat: int | None
    turn_count: int = Field(ge=0)
    result: UIScreenResultPayload | None
    latest_snapshot: JSONMapping | None
    state_payload: JSONMapping | None
    abort: UIScreenAbortPayload | None
    #: Phase 38: whose perspective this is — ``"full"``, ``"seat"`` (with
    #: ``viewer_seat``), or ``"public"``. A renderer should label a redacted view.
    view: Literal["full", "seat", "public"] = "full"
    viewer_seat: int | None = None


class UIMatchTranscriptPayload(BaseModel):
    """Transcript/history data shaped for UI consumers without presentation state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    runtime_schema_version: int = Field(ge=1)
    match_id: str = Field(min_length=1)
    game_id: str = Field(min_length=1)
    lifecycle: str = Field(min_length=1)
    players: list[UIScreenPlayerPayload]
    runtime_events: list[UIScreenRuntimeEventPayload]
    turns: list[UIScreenTurnPayload]
    abort: UIScreenAbortPayload | None
    view: Literal["full", "seat", "public"] = "full"
    viewer_seat: int | None = None


class UIMatchScreenPayload(BaseModel):
    """Combined status and transcript payload for a match screen."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    status: UIMatchStatusPayload
    transcript: UIMatchTranscriptPayload


def build_match_status(payload: JSONMapping, *, seat: int | None = None) -> JSONMapping:
    """Build deterministic screen-level status data from a runtime status payload.

    ``seat`` (Phase 38) declares whose perspective is being rendered. The UI
    never redacts — it is a pure adapter — so it refuses a payload redacted for
    anyone else rather than silently rendering the wrong seat's view.
    """

    status = validate_session_status(payload)
    _ensure_perspective(status.view, status.viewer_seat, seat, context="status")
    latest_snapshot = (
        status.latest_snapshot.model_dump(mode="json")
        if status.latest_snapshot is not None
        else None
    )
    screen_payload = UIMatchStatusPayload(
        schema_version=UI_ADAPTER_SCHEMA_VERSION,
        runtime_schema_version=status.schema_version,
        match_id=status.match_id,
        game_id=status.game_id,
        lifecycle=status.lifecycle,
        players=_dump_players(status.players),
        current_seat=status.current_seat,
        turn_count=status.turn_count,
        result=_dump_runtime_result(status.result),
        latest_snapshot=latest_snapshot,
        state_payload=_snapshot_state(latest_snapshot),
        abort=_dump_abort(status.abort),
        view=status.view,
        viewer_seat=status.viewer_seat,
    )
    return screen_payload.model_dump(mode="json")


def build_match_transcript(payload: JSONMapping, *, seat: int | None = None) -> JSONMapping:
    """Build deterministic screen-level history data from a runtime transcript payload.

    ``seat`` works as in :func:`build_match_status`.
    """

    transcript = RuntimeTranscriptPayload.model_validate(payload)
    _ensure_perspective(transcript.view, transcript.viewer_seat, seat, context="transcript")
    screen_payload = UIMatchTranscriptPayload(
        schema_version=UI_ADAPTER_SCHEMA_VERSION,
        runtime_schema_version=transcript.schema_version,
        match_id=transcript.match_id,
        game_id=transcript.game_id,
        lifecycle=transcript.lifecycle,
        players=_dump_players(transcript.players),
        runtime_events=[
            UIScreenRuntimeEventPayload(
                event_scope=event.event_scope,
                event_type=event.event_type,
                payload=event.payload,
            )
            for event in transcript.events
        ],
        turns=_dump_turns(transcript.match_transcript),
        abort=_dump_abort(transcript.abort),
        view=transcript.view,
        viewer_seat=transcript.viewer_seat,
    )
    return screen_payload.model_dump(mode="json")


def build_match_screen(
    *,
    status_payload: JSONMapping,
    transcript_payload: JSONMapping,
    seat: int | None = None,
) -> JSONMapping:
    """Combine matching runtime status and transcript payloads for a match screen."""

    status = UIMatchStatusPayload.model_validate(build_match_status(status_payload, seat=seat))
    transcript = UIMatchTranscriptPayload.model_validate(
        build_match_transcript(transcript_payload, seat=seat)
    )
    _ensure_screen_inputs_match(status, transcript)

    screen_payload = UIMatchScreenPayload(
        schema_version=UI_ADAPTER_SCHEMA_VERSION,
        status=status,
        transcript=transcript,
    )
    return screen_payload.model_dump(mode="json")


def _ensure_perspective(
    view: str, viewer_seat: int | None, seat: int | None, *, context: str
) -> None:
    """Refuse a payload redacted for a different perspective than requested.

    A full view (every perfect-information payload, and archived full
    transcripts) serves any perspective.
    """

    if view == "full":
        return
    if seat is None:
        return
    if view != "seat" or viewer_seat != seat:
        who = f"seat {viewer_seat}" if view == "seat" else "the public"
        raise ValueError(
            f"This {context} is redacted for {who}; it cannot be rendered as seat {seat}'s view."
        )


def _dump_players(
    players: Sequence[RuntimePlayerPayload],
) -> list[UIScreenPlayerPayload]:
    return [
        UIScreenPlayerPayload(
            player_id=player.player_id,
            seat=player.seat,
            label=player.label,
        )
        for player in sorted(players, key=lambda player: player.seat)
    ]


def _dump_abort(abort: RuntimeAbortPayload | None) -> UIScreenAbortPayload | None:
    if abort is None:
        return None
    return UIScreenAbortPayload(
        reason=abort.reason,
        message=abort.message,
        cause_type=abort.cause_type,
        cause_message=abort.cause_message,
    )


def _dump_runtime_result(
    result: RuntimeResultPayload | None,
) -> UIScreenResultPayload | None:
    if result is None:
        return None
    return UIScreenResultPayload(
        result_type=result.result_type,
        payload=result.payload,
    )


def _dump_match_result(result: object | None) -> UIScreenResultPayload | None:
    if result is None:
        return None
    if not isinstance(result, dict):
        raise TypeError(f"Expected turn result mapping, got {type(result).__name__}.")
    return UIScreenResultPayload(
        result_type=result["result_type"],
        payload=result.get("payload", {}),
    )


def _dump_turns(match_transcript: JSONMapping | None) -> list[UIScreenTurnPayload]:
    if match_transcript is None:
        return []

    transcript = _MatchTranscriptPayload.model_validate(match_transcript)

    screen_turns: list[UIScreenTurnPayload] = []
    for turn_index, turn in enumerate(transcript.turns, start=1):
        screen_turns.append(
            _dump_turn(turn_index=turn_index, turn=turn)
        )
    return screen_turns


def _dump_turn(*, turn_index: int, turn: _MatchTurnPayload) -> UIScreenTurnPayload:
    post_snapshot = turn.post_snapshot.model_dump(mode="json")
    return UIScreenTurnPayload(
        turn_index=turn_index,
        kind=turn.kind,
        seat=turn.seat,
        action=turn.action,
        outcome=turn.outcome,
        events=[event.model_dump(mode="json") for event in turn.events],
        result=_dump_match_result(
            turn.result.model_dump(mode="json") if turn.result is not None else None
        ),
        post_snapshot=post_snapshot,
        state_payload=_snapshot_state(post_snapshot),
    )


def _snapshot_state(snapshot: JSONMapping | None) -> JSONMapping | None:
    if snapshot is None:
        return None

    state = snapshot.get("state")
    if not isinstance(state, dict):
        raise TypeError("Snapshot state must be a mapping.")
    return state


def _ensure_screen_inputs_match(
    status: UIMatchStatusPayload,
    transcript: UIMatchTranscriptPayload,
) -> None:
    if status.match_id != transcript.match_id:
        raise ValueError(
            "UI status and transcript payloads refer to different match ids: "
            f"{status.match_id!r} != {transcript.match_id!r}."
        )
    if status.game_id != transcript.game_id:
        raise ValueError(
            "UI status and transcript payloads refer to different game ids: "
            f"{status.game_id!r} != {transcript.game_id!r}."
        )
    if (status.view, status.viewer_seat) != (transcript.view, transcript.viewer_seat):
        raise ValueError(
            "UI status and transcript payloads are different perspectives: "
            f"{(status.view, status.viewer_seat)!r} != "
            f"{(transcript.view, transcript.viewer_seat)!r}."
        )
    if status.runtime_schema_version != transcript.runtime_schema_version:
        raise ValueError(
            "UI status and transcript payloads use different runtime schema versions: "
            f"{status.runtime_schema_version!r} != {transcript.runtime_schema_version!r}."
        )
    if status.lifecycle != transcript.lifecycle:
        raise ValueError(
            "UI status and transcript payloads refer to different lifecycles: "
            f"{status.lifecycle!r} != {transcript.lifecycle!r}."
        )
    if status.turn_count != len(transcript.turns):
        raise ValueError(
            "UI status turn_count does not match transcript turn history length: "
            f"{status.turn_count!r} != {len(transcript.turns)!r}."
        )


__all__: Sequence[str] = [
    "UI_ADAPTER_SCHEMA_VERSION",
    "UIMatchScreenPayload",
    "UIMatchStatusPayload",
    "UIMatchTranscriptPayload",
    "UIScreenAbortPayload",
    "UIScreenPlayerPayload",
    "UIScreenResultPayload",
    "UIScreenRuntimeEventPayload",
    "UIScreenTurnPayload",
    "build_match_screen",
    "build_match_status",
    "build_match_transcript",
]
