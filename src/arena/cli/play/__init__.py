"""Interactive driver for live human/scripted arena sessions."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from arena.cli.policies import HumanQuit
from arena.cli.rendering import render_match_screen
from arena.core.public_view import FULL_VIEW
from arena.core.simultaneous import is_joint_node
from arena.runtime import (
    AbortReason,
    Arena,
    PlayerRecord,
    PolicyDecided,
    PolicyRetried,
    RuntimeLifecycle,
    RuntimeStateError,
    dump_runtime_transcript,
    dump_session_status,
    record_runtime_event,
)
from arena.ui import build_match_screen


def play_match(
    definition: Any,
    config: Any,
    players: tuple[PlayerRecord, ...],
    policies: Mapping[int, Any],
    *,
    out_dir: str | os.PathLike[str],
    stdin: Any = None,
    stdout: Any = None,
    arena: Arena | None = None,
    retry_sink: dict[int, list[tuple[int, str]]] | None = None,
    decision_sink: dict[int, list[tuple[int, str]]] | None = None,
    human_seats: tuple[int, ...] = (),
) -> int:
    """Run one interactive or scripted match and write JSON artefacts.

    Returns 0 on terminal completion, 1 on abort.

    For a hidden-information game the screen shows only what the human at the
    terminal may see (Phase 39): one human seat gets its own view; with two
    humans sharing the terminal (hot-seat) the seat to move is shown its view,
    which cannot hide anything from someone watching over its shoulder; with no
    human it is the public view. The finished screen shows everything. The JSON
    artefacts are always the full record: they are the operator's.

    retry_sink maps seat -> list of (attempt, reason) tuples appended by agent
    callbacks. After each complete_turn the driver drains the sink and records
    PolicyRetried runtime events into the session.
    """
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout
    if arena is None:
        arena = Arena()

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    session = arena.create_session(definition, config, players, policies)
    session = arena.start_session(session)

    while session.lifecycle is RuntimeLifecycle.RUNNING:
        _render(session, stdout, _viewer(session, human_seats))
        local_match = session.local_match
        if local_match is not None and is_joint_node(local_match.rules_engine, local_match.state):
            # A simultaneous round (Phase 41): every acting seat chooses, then
            # the round is applied at once. The screen is not redrawn between
            # the seats, so an agent's choice is not shown before the other's.
            try:
                session = arena.step_session(session)
            except (HumanQuit, KeyboardInterrupt) as exc:
                abort_reason, msg = _abort_info(exc)
                session = arena.abort_session(session, reason=abort_reason, message=msg)
                break
        else:
            try:
                requested_session, seat = arena.request_turn(session)
            except RuntimeStateError:
                break
            try:
                session = arena.complete_turn(requested_session, seat)
            except (HumanQuit, KeyboardInterrupt) as exc:
                abort_reason, msg = _abort_info(exc)
                session = arena.abort_session(
                    requested_session, reason=abort_reason, message=msg
                )
                break

        if retry_sink is not None:
            session = _drain_retry_sink(session, retry_sink)
        if decision_sink is not None:
            session = _drain_decision_sink(session, decision_sink)

    _render(session, stdout)

    status_payload = dump_session_status(session)
    transcript_payload = dump_runtime_transcript(session)

    (out_path / "status.json").write_text(
        json.dumps(status_payload, indent=2), encoding="utf-8"
    )
    (out_path / "transcript.json").write_text(
        json.dumps(transcript_payload, indent=2), encoding="utf-8"
    )

    return 0 if session.lifecycle is RuntimeLifecycle.FINISHED else 1


def _drain_retry_sink(
    session: Any,
    retry_sink: dict[int, list[tuple[int, str]]],
) -> Any:
    for seat, entries in retry_sink.items():
        for attempt, reason in entries:
            event = PolicyRetried(
                match_id=session.match_id,
                seat=seat,
                attempt=attempt,
                reason_summary=reason,
            )
            session = record_runtime_event(session, event)
        entries.clear()
    return session


def _drain_decision_sink(
    session: Any,
    decision_sink: dict[int, list[tuple[int, str]]],
) -> Any:
    for seat, entries in decision_sink.items():
        for attempt, thought in entries:
            event = PolicyDecided(
                match_id=session.match_id,
                seat=seat,
                attempt=attempt,
                thought=thought,
            )
            session = record_runtime_event(session, event)
        entries.clear()
    return session


def _viewer(session: Any, human_seats: tuple[int, ...]) -> Any:
    """Whose view the live screen shows; see :func:`play_match`."""

    if not session.definition.has_hidden_information:
        return FULL_VIEW
    if len(human_seats) == 1:
        return human_seats[0]
    local_match = session.local_match
    if human_seats and local_match is not None:
        engine = local_match.rules_engine
        if not engine.is_terminal(local_match.state):
            return engine.current_seat(local_match.state)
    return None


def _render(session: Any, stdout: Any, viewer: Any = FULL_VIEW) -> None:
    status_payload = dump_session_status(session, viewer=viewer)
    transcript_payload = dump_runtime_transcript(session, viewer=viewer)
    screen = build_match_screen(
        status_payload=status_payload,
        transcript_payload=transcript_payload,
    )
    stdout.write(render_match_screen(screen))
    stdout.write("\n")
    stdout.flush()


def _abort_info(exc: BaseException) -> tuple[AbortReason, str]:
    if isinstance(exc, HumanQuit) and exc.reason == "user_interrupt":
        return AbortReason.USER_INTERRUPT, "interrupted by user"
    if isinstance(exc, KeyboardInterrupt):
        return AbortReason.USER_INTERRUPT, "interrupted by user"
    return AbortReason.USER_QUIT, "user requested quit"


__all__: tuple[str, ...] = ("play_match",)
