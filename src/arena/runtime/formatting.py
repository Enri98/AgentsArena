"""Human-readable formatting helpers for runtime payloads."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from arena.core.serializer import JSONMapping
from arena.match.transcript import MatchResultPayload, MatchTranscriptPayload
from arena.runtime.payloads import (
    RuntimeAbortPayload,
    RuntimeEventPayload,
    RuntimeResultPayload,
    RuntimeSessionStatusPayload,
    RuntimeTranscriptPayload,
    validate_session_status,
)


def format_session_status(payload: JSONMapping) -> str:
    """Format a runtime session status payload as deterministic readable text."""

    status = validate_session_status(payload)
    return _format_session_status(status)


def format_runtime_transcript(payload: JSONMapping) -> str:
    """Format a runtime transcript payload as deterministic readable text."""

    transcript = RuntimeTranscriptPayload.model_validate(payload)
    return _format_runtime_transcript(transcript)


def format_runtime_session_report(
    *,
    status_payload: JSONMapping,
    transcript_payload: JSONMapping,
) -> str:
    """Format matching status and transcript payloads into one deterministic report."""

    status = validate_session_status(status_payload)
    transcript = RuntimeTranscriptPayload.model_validate(transcript_payload)
    _ensure_report_payloads_match(status, transcript)

    return "\n\n".join(
        (
            _format_session_status(status),
            _format_runtime_transcript(transcript),
        )
    )


def _format_session_status(status: RuntimeSessionStatusPayload) -> str:
    lines = [
        "Runtime session status",
        f"Match: {status.match_id}",
        f"Game: {status.game_id}",
        f"Lifecycle: {status.lifecycle}",
        "Players:",
    ]
    lines.extend(_format_players(player.model_dump(mode="json") for player in status.players))
    lines.append(f"Turn count: {status.turn_count}")

    if status.current_seat is None:
        lines.append("Current turn: none")
    else:
        lines.append(f"Current turn: seat {status.current_seat}")

    lines.append(f"Result: {_format_result(status.result)}")

    if status.abort is not None:
        lines.extend(_format_abort(status.abort))

    if status.latest_snapshot is None:
        lines.append("Latest snapshot: none")
    else:
        lines.append(
            "Latest snapshot: "
            f"schema_version={status.latest_snapshot.schema_version}, "
            f"game_id={status.latest_snapshot.game_id}"
        )

    return "\n".join(lines)


def _format_runtime_transcript(transcript: RuntimeTranscriptPayload) -> str:
    lines = [
        "Runtime transcript",
        f"Match: {transcript.match_id}",
        f"Game: {transcript.game_id}",
        f"Lifecycle: {transcript.lifecycle}",
        "Players:",
    ]
    lines.extend(_format_players(player.model_dump(mode="json") for player in transcript.players))

    if transcript.abort is not None:
        lines.extend(_format_abort(transcript.abort))

    lines.append("Runtime events:")
    lines.extend(_format_runtime_events(transcript.events))
    lines.append("Turn history:")
    lines.extend(_format_turn_history(transcript.match_transcript))

    return "\n".join(lines)


def _ensure_report_payloads_match(
    status: RuntimeSessionStatusPayload,
    transcript: RuntimeTranscriptPayload,
) -> None:
    if status.match_id != transcript.match_id:
        raise ValueError(
            "Runtime status and transcript payloads refer to different match ids: "
            f"{status.match_id!r} != {transcript.match_id!r}."
        )
    if status.game_id != transcript.game_id:
        raise ValueError(
            "Runtime status and transcript payloads refer to different game ids: "
            f"{status.game_id!r} != {transcript.game_id!r}."
        )
    if status.lifecycle != transcript.lifecycle:
        raise ValueError(
            "Runtime status and transcript payloads refer to different lifecycles: "
            f"{status.lifecycle!r} != {transcript.lifecycle!r}."
        )


def _format_players(players: Iterable[JSONMapping]) -> list[str]:
    return [
        (
            f"- seat {player['seat']}: "
            f"{player['label'] or '<unlabeled>'} "
            f"({player['player_id']})"
        )
        for player in sorted(players, key=lambda player: player["seat"])
    ]


def _format_abort(abort: RuntimeAbortPayload) -> list[str]:
    lines = [
        "Abort:",
        f"- reason: {abort.reason}",
        f"- message: {abort.message}",
    ]
    if abort.cause_type is not None:
        lines.append(f"- cause: {abort.cause_type}: {abort.cause_message}")
    else:
        lines.append("- cause: none")
    return lines


def _format_result(result: RuntimeResultPayload | None) -> str:
    if result is None:
        return "ongoing"
    payload_suffix = f" {_format_json(result.payload)}" if result.payload else ""
    return f"{result.result_type}{payload_suffix}"


def _format_runtime_events(events: Sequence[RuntimeEventPayload]) -> list[str]:
    if not events:
        return ["- none"]
    return [
        f"- {event.event_type}: {_format_json(event.payload)}"
        for event in events
    ]


def _format_turn_history(match_transcript: JSONMapping | None) -> list[str]:
    if match_transcript is None:
        return ["- none"]

    transcript = MatchTranscriptPayload.model_validate(match_transcript)
    turns = transcript.turns
    if not turns:
        return ["- none"]

    lines: list[str] = []
    for turn_number, turn in enumerate(turns, start=1):
        action = turn.action
        events = turn.events
        result = turn.result
        lines.append(
            f"- turn {turn_number}: seat {turn.seat} "
            f"action={_format_json(action)}"
        )
        if events:
            event_text = ", ".join(
                f"{event.event_type} {_format_json(event.payload)}"
                for event in events
            )
        else:
            event_text = "none"
        lines.append(f"  game events: {event_text}")
        lines.append(f"  result: {_format_match_result(result)}")
    return lines


def _format_match_result(result: MatchResultPayload | None) -> str:
    if result is None:
        return "ongoing"
    result_payload = result.model_dump(mode="json")
    payload = result_payload["payload"]
    payload_suffix = f" {_format_json(payload)}" if payload else ""
    return f"{result_payload['result_type']}{payload_suffix}"


def _format_json(payload: JSONMapping) -> str:
    return json.dumps(payload, sort_keys=True, separators=(", ", ": "))


__all__: Sequence[str] = [
    "format_runtime_session_report",
    "format_runtime_transcript",
    "format_session_status",
]
