"""Async runtime bridge: drives one match end-to-end over a pair of WebSocket connections.

Bridging approach — imperative async driver
-------------------------------------------
We do NOT use asyncio.to_thread + WebSocketPolicy because the runtime primitives
(start_session, apply_match_action) are fast in-process calls; there is no benefit
to running them in a worker thread, and doing so would complicate broadcast ordering.

Instead this module drives the session turn-by-turn from a single async coroutine
(run_match), called from the seat-1 WebSocket handler.  The seat-0 handler idles
until the match is complete.

Message sends use an asyncio.Lock per connection so that run_match can safely call
ws.send_text on both WebSocket objects from the seat-1 handler coroutine without
racing with the seat-0 handler.  (In practice only run_match sends after the match
starts, so the lock is mostly uncontested.)

Phase 32 TODO items (not implemented here):
- Per-turn deadline enforcement (deadline_ms in observation_request is sent but not
  enforced server-side; enforcement lives in arena.server per CLAUDE.md).
- Real resume_token rotation; current stub is a static derived value.
- Heartbeat ping/pong send loop (§8.10).
- Reconnection grace period and transcript replay on resume.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

from arena.adapters.in_process import (
    ActionResponsePayload,
    DomainErrorPayload,
    build_observation_request,
    dump_domain_error,
    load_action_response,
)
from arena.adapters.websocket import (
    WIRE_SCHEMA_VERSION,
    ActionRejectedEnvelope,
    ErrorEnvelope,
    MatchAbortedEnvelope,
    MatchFinishedEnvelope,
    MatchStateEnvelope,
    ObservationRequestEnvelope,
    TurnCommittedEnvelope,
    WelcomeEnvelope,
    dumps,
    loads,
)
from arena.adapters.websocket.errors import WireProtocolError
from arena.adapters.websocket.messages import (
    ActionRejectedBody,
    ErrorBody,
    MatchAbortedBody,
    MatchFinishedBody,
    MatchStateBody,
    ObservationRequestBody,
    PlayerInfoBody,
    TurnCommittedBody,
    WelcomeBody,
)
from arena.core.exceptions import ArenaCoreError
from arena.match.local_match import apply_match_action
from arena.runtime.models import (
    AbortMetadata,
    AbortReason,
    MatchFinished,
    RuntimeLifecycle,
    TurnAccepted,
)
from arena.runtime.payloads import (
    RuntimeAbortPayload,
    RuntimeTranscriptPayload,
    dump_runtime_transcript,
)
from arena.runtime.session import MatchSession

if TYPE_CHECKING:
    from fastapi import WebSocket

    from arena.server.registry import Match

logger = logging.getLogger(__name__)

WS_CLOSE_NORMAL = 1000


@dataclass
class SeatConnection:
    """Mutable per-seat state for one active WebSocket connection."""

    websocket: "WebSocket"
    seat: int
    # Lock serialises concurrent send_text calls on this WS from different coroutines.
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _make_resume_token(match_id: str, seat: int) -> str:
    # Phase 32 TODO: rotate this on every successful resume.
    raw = f"{match_id}:seat:{seat}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _build_player_info(match: "Match") -> list[PlayerInfoBody]:
    return [
        PlayerInfoBody(player_id=p.player_id, label=p.label, seat=p.seat)
        for p in match.players
    ]


def _build_match_state_body(
    session: MatchSession,
    *,
    override_lifecycle: str | None = None,
) -> MatchStateBody:
    lc = override_lifecycle or session.lifecycle.value
    local_match = session.local_match
    current_seat = None
    turn_count = 0
    abort_dict = None

    if local_match is not None:
        turn_count = len(local_match.turns)
        if not local_match.rules_engine.is_terminal(local_match.state):
            current_seat = local_match.rules_engine.current_seat(local_match.state)

    if session.abort is not None:
        abort_dict = _dump_abort_dict(session.abort)

    return MatchStateBody(
        lifecycle=lc,
        current_seat=current_seat,
        turn_count=turn_count,
        result=None,
        abort=abort_dict,
    )


def _dump_abort_dict(abort: AbortMetadata) -> dict:
    payload = RuntimeAbortPayload(
        reason=abort.reason.value,
        message=abort.message,
        cause_type=abort.cause_type,
        cause_message=abort.cause_message,
    )
    return payload.model_dump(mode="json")


def _build_transcript_payload(session: MatchSession) -> RuntimeTranscriptPayload:
    raw = dump_runtime_transcript(session)
    return RuntimeTranscriptPayload.model_validate(raw)


async def _send(conn: SeatConnection, envelope) -> None:
    """Send one envelope to a single seat, serialised via the connection lock."""
    text = dumps(envelope)
    async with conn.send_lock:
        try:
            await conn.websocket.send_text(text)
        except Exception as exc:
            logger.debug("send to seat %d failed: %s", conn.seat, exc)


async def _broadcast(conns: tuple[SeatConnection, SeatConnection], envelope) -> None:
    """Send one envelope to both seats sequentially.

    Sends to seat 0 first, then seat 1.  This ordering must be preserved:
    the Starlette TestClient serialises portal.call across threads; if the
    test drains seat 1 before seat 0, seat 0's message will be delivered on
    the next portal scheduling round, which is fine as long as we do not
    close before that happens.
    """
    text = dumps(envelope)
    for conn in conns:
        async with conn.send_lock:
            try:
                await conn.websocket.send_text(text)
            except Exception as exc:
                logger.debug("broadcast to seat %d failed: %s", conn.seat, exc)


async def _broadcast_match_state(
    conns: tuple[SeatConnection, SeatConnection],
    session: MatchSession,
    *,
    override_lifecycle: str | None = None,
) -> None:
    body = _build_match_state_body(session, override_lifecycle=override_lifecycle)
    env = MatchStateEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=session.match_id,
        payload=body,
    )
    await _broadcast(conns, env)


async def _broadcast_turn_committed(
    conns: tuple[SeatConnection, SeatConnection],
    session: MatchSession,
) -> None:
    local_match = session.local_match
    if local_match is None or not local_match.turns:
        return
    last_turn = local_match.turns[-1]
    post_snap = last_turn.post_snapshot
    post_snapshot_dict = post_snap.model_dump(mode="json")
    turn_record_dict = {
        "turn_index": len(local_match.turns) - 1,
        "seat": last_turn.seat,
        "action": session.definition.serializer.dump_action(last_turn.action),
        "events": [e.__class__.__name__ for e in last_turn.events],
        "post_snapshot": post_snapshot_dict,
    }
    body = TurnCommittedBody(
        turn_record=turn_record_dict,
        post_snapshot=post_snapshot_dict,
        events=[],
    )
    env = TurnCommittedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=session.match_id,
        payload=body,
    )
    await _broadcast(conns, env)


async def _broadcast_match_finished(
    conns: tuple[SeatConnection, SeatConnection],
    session: MatchSession,
) -> None:
    transcript = _build_transcript_payload(session)
    body = MatchFinishedBody(result={}, transcript=transcript)
    env = MatchFinishedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=session.match_id,
        payload=body,
    )
    await _broadcast(conns, env)


async def _broadcast_match_aborted(
    conns: tuple[SeatConnection, SeatConnection],
    session: MatchSession,
) -> None:
    transcript = _build_transcript_payload(session)
    abort_payload = RuntimeAbortPayload(
        reason=session.abort.reason.value,
        message=session.abort.message,
        cause_type=session.abort.cause_type,
        cause_message=session.abort.cause_message,
    )
    body = MatchAbortedBody(abort=abort_payload, transcript=transcript)
    env = MatchAbortedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=session.match_id,
        payload=body,
    )
    await _broadcast(conns, env)


async def _close_both(
    conns: tuple[SeatConnection, SeatConnection],
    code: int,
    reason: str,
) -> None:
    """Close both WebSocket connections."""
    for conn in conns:
        try:
            await conn.websocket.close(code=code, reason=reason)
        except Exception:
            pass


async def _receive_action(
    active_conn: SeatConnection,
    match_id: str,
    committed_turn_ids: set[str],
    rejected_turn_ids: set[str],
) -> tuple[str | None, ActionResponsePayload | None, str | None]:
    """Wait for a valid action_response frame from the active seat.

    Returns (turn_id, payload, error_msg).  error_msg non-None → send error back.
    Returns (None, None, "disconnected") on WS close.
    Duplicate turn_ids are silently dropped — returns (None, None, None) meaning retry.
    """
    while True:
        try:
            raw = await active_conn.websocket.receive_text()
        except Exception:
            return None, None, "disconnected"

        try:
            envelope = loads(raw)
        except WireProtocolError as exc:
            return None, None, str(exc)

        if envelope.type != "action_response":
            if envelope.type not in ("ping", "pong"):
                return None, None, f"expected action_response, got {envelope.type!r}"
            continue

        turn_id = envelope.turn_id or str(uuid.uuid4())

        if turn_id in committed_turn_ids or turn_id in rejected_turn_ids:
            logger.debug("Dropped duplicate turn_id %s for match %s", turn_id, match_id)
            continue

        return turn_id, envelope.payload.action_response, None


async def run_match(
    match: "Match",
    conns: tuple[SeatConnection, SeatConnection],
) -> None:
    """Drive a match to completion over two WebSocket connections.

    Must be called only after both seats have completed the hello/welcome handshake.
    Mutates match.session on each turn (Match is a mutable dataclass).
    """
    arena = match.arena
    session = match.session

    session = arena.start_session(session)
    match.session = session

    if session.lifecycle is RuntimeLifecycle.ABORTED:
        await _broadcast_match_state(conns, session)
        await _broadcast_match_aborted(conns, session)
        await _close_both(conns, WS_CLOSE_NORMAL, "match_aborted")
        return

    await _broadcast_match_state(conns, session)

    committed_turn_ids: set[str] = set()
    rejected_turn_ids: set[str] = set()

    while session.lifecycle is RuntimeLifecycle.RUNNING:
        local_match = session.local_match
        assert local_match is not None

        if local_match.rules_engine.is_terminal(local_match.state):
            break

        active_seat = local_match.rules_engine.current_seat(local_match.state)
        active_conn = conns[active_seat]

        obs_request = build_observation_request(local_match)
        obs_body = ObservationRequestBody(
            observation_request=obs_request,
            deadline_ms=match.per_turn_deadline_ms,  # Phase 32: enforce this
        )
        obs_env = ObservationRequestEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            match_id=session.match_id,
            seat=active_seat,
            payload=obs_body,
        )
        await _send(active_conn, obs_env)

        retries_left = match.per_action_retry_budget
        action_accepted = False

        while not action_accepted:
            turn_id, action_resp, error_msg = await _receive_action(
                active_conn, session.match_id, committed_turn_ids, rejected_turn_ids
            )

            if error_msg == "disconnected":
                session = arena.abort_session(
                    session,
                    reason=AbortReason.CANCELLED,
                    message="Seat disconnected during turn.",
                )
                match.session = session
                await _broadcast_match_state(conns, session)
                await _broadcast_match_aborted(conns, session)
                await _close_both(conns, WS_CLOSE_NORMAL, "peer_disconnected")
                return

            if error_msg is not None:
                # Non-fatal parse error: send error envelope, don't consume retry budget.
                err_env = ErrorEnvelope(
                    schema_version=WIRE_SCHEMA_VERSION,
                    match_id=session.match_id,
                    payload=ErrorBody(code="malformed_envelope", message=error_msg),
                )
                await _send(active_conn, err_env)
                continue

            assert turn_id is not None
            assert action_resp is not None

            try:
                typed_action = load_action_response(session.definition, action_resp)
                next_match = apply_match_action(local_match, active_seat, typed_action)
            except ArenaCoreError as exc:
                domain_err = dump_domain_error(exc)
                rejected_turn_ids.add(turn_id)

                if retries_left == 0:
                    # §8.6: rejected(0) → match_state(aborted) → match_aborted → close
                    rej_env = _make_rejected_env(session, active_seat, turn_id, domain_err, 0)
                    await _send(active_conn, rej_env)
                    session = arena.abort_session(
                        session,
                        reason=AbortReason.ADAPTER_ERROR,
                        message="Retry budget exhausted.",
                    )
                    match.session = session
                    await _broadcast_match_state(conns, session)
                    await _broadcast_match_aborted(conns, session)
                    await _close_both(conns, WS_CLOSE_NORMAL, "adapter_error")
                    return

                retries_left -= 1
                rej_env = _make_rejected_env(
                    session, active_seat, turn_id, domain_err, retries_left
                )
                await _send(active_conn, rej_env)
                continue

            except Exception as exc:
                domain_err = DomainErrorPayload(
                    code="adapter_error",
                    message=str(exc) or "Unknown error",
                )
                rejected_turn_ids.add(turn_id)

                if retries_left == 0:
                    rej_env = _make_rejected_env(session, active_seat, turn_id, domain_err, 0)
                    await _send(active_conn, rej_env)
                    session = arena.abort_session(
                        session, reason=AbortReason.ADAPTER_ERROR, message="Retry budget exhausted."
                    )
                    match.session = session
                    await _broadcast_match_state(conns, session)
                    await _broadcast_match_aborted(conns, session)
                    await _close_both(conns, WS_CLOSE_NORMAL, "adapter_error")
                    return

                retries_left -= 1
                rej_env = _make_rejected_env(
                    session, active_seat, turn_id, domain_err, retries_left
                )
                await _send(active_conn, rej_env)
                continue

            # Action accepted.
            committed_turn_ids.add(turn_id)
            action_accepted = True

            new_events = session.events + (
                TurnAccepted(
                    match_id=session.match_id,
                    seat=active_seat,
                    turn_index=len(next_match.turns),
                ),
            )
            new_lifecycle = RuntimeLifecycle.RUNNING
            if next_match.rules_engine.is_terminal(next_match.state):
                new_lifecycle = RuntimeLifecycle.FINISHED
                new_events = new_events + (MatchFinished(match_id=session.match_id),)

            session = dc_replace(
                session,
                local_match=next_match,
                lifecycle=new_lifecycle,
                events=new_events,
            )
            match.session = session

            await _broadcast_turn_committed(conns, session)
            await _broadcast_match_state(conns, session)

    # Match reached terminal state.
    if session.lifecycle is RuntimeLifecycle.FINISHED:
        await _broadcast_match_finished(conns, session)
    else:
        await _broadcast_match_aborted(conns, session)

    await _close_both(conns, WS_CLOSE_NORMAL, "normal_closure")


def _make_rejected_env(
    session: MatchSession,
    active_seat: int,
    turn_id: str,
    domain_err: DomainErrorPayload,
    retries_remaining: int,
) -> ActionRejectedEnvelope:
    return ActionRejectedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=session.match_id,
        seat=active_seat,
        turn_id=turn_id,
        payload=ActionRejectedBody(
            turn_id=turn_id,
            error=domain_err,
            retries_remaining=retries_remaining,
        ),
    )


async def send_welcome(conn: SeatConnection, match: "Match") -> None:
    """Send a welcome envelope to one seat after a successful hello handshake."""
    players = _build_player_info(match)
    match_config_dict = match.definition.serializer.dump_config(match.match_config)

    body = WelcomeBody(
        match_id=match.match_id,
        game_id=match.game_id,
        game_schema_version=1,
        seat=conn.seat,
        lifecycle=match.session.lifecycle.value,
        schema_version=WIRE_SCHEMA_VERSION,
        negotiated_schema_version=WIRE_SCHEMA_VERSION,
        resume_token=_make_resume_token(match.match_id, conn.seat),  # Phase 32: rotate
        per_turn_deadline_ms=match.per_turn_deadline_ms,
        per_action_retry_budget=match.per_action_retry_budget,
        disconnect_grace_ms=match.disconnect_grace_ms,
        players=players,
        match_config=match_config_dict,
    )
    env = WelcomeEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=match.match_id,
        seat=conn.seat,
        payload=body,
    )
    await _send(conn, env)
