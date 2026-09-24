"""File-based loader and frame entrypoint for the terminal replay viewer."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Sequence
from typing import Any

from arena.cli.rendering import render_match_screen
from arena.ui import build_match_screen


def _load(
    status_path: str | os.PathLike[str],
    transcript_path: str | os.PathLike[str],
    seat: int | None,
) -> dict[str, Any]:
    """Read the files and build the screen, as seat ``seat`` saw it if given.

    A saved full transcript of a hidden-information game is redacted to that
    seat's view here. A file that is already a seat's view is rendered as is, and
    the UI refuses it if it belongs to a different seat.
    """

    with open(status_path, encoding="utf-8") as fh:
        status_payload: dict[str, Any] = json.load(fh)
    with open(transcript_path, encoding="utf-8") as fh:
        transcript_payload: dict[str, Any] = json.load(fh)

    if seat is not None:
        from arena.games import build_default_registry
        from arena.runtime.payloads import redact_runtime_transcript, redact_session_status

        # Each file is redacted on its own: a full status beside a seat-view
        # transcript would otherwise show the full state.
        definition = build_default_registry().get(transcript_payload["game_id"])
        if transcript_payload.get("view", "full") == "full":
            transcript_payload = redact_runtime_transcript(definition, transcript_payload, seat)
        if status_payload.get("view", "full") == "full":
            status_payload = redact_session_status(definition, status_payload, seat)

    return build_match_screen(
        status_payload=status_payload,
        transcript_payload=transcript_payload,
        seat=seat,
    )


def render_session_from_files(
    status_path: str | os.PathLike[str],
    transcript_path: str | os.PathLike[str],
    *,
    turn: int | None = None,
    seat: int | None = None,
) -> str:
    """Read status and transcript JSON files and render one or the latest frame.

    When *turn* is None, the latest complete screen is rendered.
    When *turn* is an integer, the board and turn-history cursor reflect frame N
    while the status header always reflects the latest session state.
    When *seat* is given, everything is shown as that seat saw it (Phase 38).
    """
    screen = _load(status_path, transcript_path, seat)

    if turn is None:
        return render_match_screen(screen)

    turns: list[Any] = screen["transcript"]["turns"]
    n_turns = len(turns)
    if not (0 <= turn < n_turns):
        raise IndexError(
            f"Turn index {turn!r} is out of range for a transcript with {n_turns} turn(s)."
        )

    return _render_frame(screen, turn)


def render_all_frames(
    status_path: str | os.PathLike[str],
    transcript_path: str | os.PathLike[str],
    *,
    seat: int | None = None,
) -> str:
    """Render every turn frame separated by '=== Turn N ===' headers."""
    screen = _load(status_path, transcript_path, seat)

    turns: list[Any] = screen["transcript"]["turns"]
    sections: list[str] = []
    for idx in range(len(turns)):
        sections.append(f"=== Turn {idx} ===")
        sections.append(_render_frame(screen, idx))

    return "\n".join(sections)


def _render_frame(screen: dict[str, Any], turn: int) -> str:
    """Render a single frame N: status is latest, board and history are at frame N."""
    frame = copy.deepcopy(screen)

    turns: list[Any] = frame["transcript"]["turns"]

    frame_turn = turns[turn]
    state_payload = frame_turn.get("state_payload")

    frame["status"]["state_payload"] = state_payload
    if state_payload is not None:
        frame["status"]["latest_snapshot"] = frame_turn.get("post_snapshot")

    frame["transcript"]["turns"] = turns[: turn + 1]

    return render_match_screen(frame)


__all__: Sequence[str] = (
    "render_all_frames",
    "render_session_from_files",
)
