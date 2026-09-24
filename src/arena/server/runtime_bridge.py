"""Async runtime bridge: drives one match end-to-end over a pair of WebSocket connections.

Bridging approach — imperative async driver
-------------------------------------------
We do NOT use asyncio.to_thread + WebSocketPolicy because the runtime primitives
(start_session, apply_match_action) are fast in-process calls; there is no benefit
to running them in a worker thread, and doing so would complicate broadcast ordering.

Instead this module drives the session turn-by-turn from a single async coroutine
(run_match), called from the seat-1 WebSocket handler.  The seat-0 handler idles
until the match is complete.

Sending (Phase 36 Slice 2)
--------------------------
Recipients live in a MatchConnections registry rather than a fixed 2-tuple, so
spectators can attach without touching the broadcast helpers.

Each connection owns a bounded outbox drained by its own writer task.  run_match
enqueues and never awaits a socket.  Before this, _broadcast awaited send_text on
each connection in turn from inside run_match: one blocked send suspended the
driver while the per-turn deadline kept running, so a slow or stalled reader
aborted the match and the abort was attributed to whichever seat was active.
A recipient that falls OUTBOX_MAXSIZE frames behind has frames dropped rather
than being allowed to stall the match.

An asyncio.Lock per connection still serialises the actual send_text calls, and
the writer is the only thing that touches the socket once a match is running.
Terminal frames are queued like any other, so _close_both drains each outbox
before closing — otherwise clients would miss match_finished / match_aborted.

Phase 32 features implemented here:
- Per-turn deadline enforcement: asyncio.wait_for wraps _receive_action per turn.
- Real resume_token rotation: secrets.token_urlsafe(16) on every send_welcome call.
- Heartbeat ping/pong loop: _heartbeat_loop sends PingEnvelope every interval_s.
- Heartbeat: only the active seat is pinged per turn; off-turn disconnects caught at next turn.
- Disconnect grace period: waits for reconnect_event before aborting.
- Reconnect path: new SeatConnection replaces old one; transcript replay sent.
"""

from __future__ import annotations

import asyncio
import secrets as _secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING, Any

import structlog

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
    PingEnvelope,
    SpectatorWelcomeEnvelope,
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
    PingBody,
    PlayerInfoBody,
    SpectatorWelcomeBody,
    TurnCommittedBody,
    WelcomeBody,
)
from arena.core.chance import dump_chance_outcome
from arena.core.exceptions import ArenaCoreError
from arena.match.local_match import TURN_KIND_CHANCE, apply_match_action
from arena.match.transcript import dump_domain_event
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
from arena.server.rate_limits import CLOSE_RATE_LIMITED, RateLimitExceeded

if TYPE_CHECKING:
    from fastapi import WebSocket

    from arena.server.registry import Match

logger = structlog.get_logger(__name__)

WS_CLOSE_NORMAL = 1000
#: Frames a single connection may have in flight before it is considered
#: too slow. Well above any legitimate burst: one turn produces ~3 frames.
OUTBOX_MAXSIZE = 64
HEARTBEAT_CLOSE_CODE = 4408


@dataclass
class SeatConnection:
    """Mutable per-seat state for one active WebSocket connection."""

    websocket: "WebSocket"
    seat: int
    # Lock serialises concurrent send_text calls on this WS from different coroutines.
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Heartbeat tracking (Phase 32).
    pong_event: asyncio.Event = field(default_factory=asyncio.Event)
    pending_pong_nonce: str | None = None
    consecutive_heartbeat_misses: int = 0
    heartbeat_timed_out: bool = False
    # Phase 36 Slice 2: bounded outbox drained by a per-connection writer task,
    # so one slow reader cannot suspend the match driver.
    outbox: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=OUTBOX_MAXSIZE))
    writer_task: "asyncio.Task | None" = None
    outbox_overflowed: bool = False


@dataclass
class SpectatorConnection:
    """A read-only attachment to a match (Phase 36 Slice 3).

    Deliberately shaped like SeatConnection so _send, _writer_loop and
    _stop_writer work on it unchanged; ``seat`` is None because a spectator
    holds none, and the send path only uses it for logging.

    Spectators are never sent observation_request or action_rejected, and an
    overflowing spectator is dropped rather than allowed to slow the match.
    """

    websocket: "WebSocket"
    seat: int | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    outbox: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=OUTBOX_MAXSIZE))
    writer_task: "asyncio.Task | None" = None
    outbox_overflowed: bool = False


class MatchConnections:
    """Live recipient registry for one match (Phase 36 Slice 2).

    Replaces the fixed ``tuple[SeatConnection, SeatConnection]`` that used to be
    threaded through ``run_match`` and every broadcast helper.

    Two deliberate properties:

    * Seats stay addressable by index, so existing ``conns[active_seat]`` call
      sites are unchanged.
    * Iteration yields every broadcast recipient. That is what lets Slice 3
      attach spectators without editing the broadcast helpers again, and what
      Phase 38 needs when a broadcast stops being one identical payload.

    Seat membership is fixed at two; spectators come and go. Mutating methods are
    only ever called from the single event loop that owns the match.
    """

    __slots__ = ("_seats", "_spectators")

    def __init__(self, seat0: SeatConnection, seat1: SeatConnection) -> None:
        self._seats: dict[int, SeatConnection] = {0: seat0, 1: seat1}
        self._spectators: list[Any] = []

    def __getitem__(self, seat: int) -> SeatConnection:
        return self._seats[seat]

    def __iter__(self) -> "Iterator[Any]":
        yield from self._seats.values()
        # Copied: a slow spectator may be dropped mid-broadcast.
        yield from tuple(self._spectators)

    def __len__(self) -> int:
        return len(self._seats) + len(self._spectators)

    def seats(self) -> tuple[SeatConnection, ...]:
        """The two seat connections, in seat order."""

        return (self._seats[0], self._seats[1])

    def replace_seat(self, seat: int, conn: SeatConnection) -> None:
        """Swap in a reconnected seat's new connection."""

        self._seats[seat] = conn

    def add_spectator(self, conn: Any) -> None:
        self._spectators.append(conn)

    def remove_spectator(self, conn: Any) -> None:
        try:
            self._spectators.remove(conn)
        except ValueError:
            pass

    def spectators(self) -> tuple[Any, ...]:
        return tuple(self._spectators)


def _get_match_conns(app_state: Any) -> dict[str, "MatchConnections"]:
    """Per-match connection registries, keyed by match_id.

    Published on app.state so a spectator handler (Slice 3) can attach to a
    running match without reaching into the seat handler that started it.
    Released by create_app's eviction hook.
    """
    if not hasattr(app_state, "_ws_match_conns"):
        app_state._ws_match_conns = {}
    return app_state._ws_match_conns


def _get_pending_spectators(app_state: Any) -> dict[str, list["SpectatorConnection"]]:
    """Spectators that attached before the match had a connection registry.

    A spectator may arrive before both seats do, at which point there is no
    MatchConnections yet. It parks here and the seat handler folds it in when it
    builds the registry. Released by create_app's eviction hook.
    """
    if not hasattr(app_state, "_ws_pending_spectators"):
        app_state._ws_pending_spectators = {}
    return app_state._ws_pending_spectators


async def send_spectator_welcome(
    conn: "SpectatorConnection",
    match: "Match",
) -> None:
    """Send spectator_welcome, carrying the attach-time history.

    Bundling the transcript into the welcome means a spectator joining mid-match
    can render immediately. There is no separate "history so far" message for a
    running match, and inventing one would be a wire addition this phase avoids.
    """

    session = match.session
    local_match = session.local_match
    turn_count = len(local_match.turns) if local_match is not None else 0

    transcript: RuntimeTranscriptPayload | None = None
    if local_match is not None:
        try:
            transcript = _build_transcript_payload(session)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("spectator_transcript_failed", error=str(exc))

    body = SpectatorWelcomeBody(
        match_id=match.match_id,
        game_id=match.game_id,
        game_schema_version=1,
        lifecycle=session.lifecycle.value,
        schema_version=WIRE_SCHEMA_VERSION,
        negotiated_schema_version=WIRE_SCHEMA_VERSION,
        players=_build_player_info(match),
        turn_count=turn_count,
        transcript=transcript,
    )
    env = SpectatorWelcomeEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=match.match_id,
        payload=body,
    )
    await _send(conn, env)


def _make_resume_token() -> str:
    """Generate an opaque, unpredictable resume token (rotated on every call)."""
    return _secrets.token_urlsafe(16)


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


async def _send_now(conn: SeatConnection, text: str) -> bool:
    """Write one frame straight to the socket. Returns whether it went out."""

    async with conn.send_lock:
        try:
            await conn.websocket.send_text(text)
            return True
        except Exception as exc:
            logger.debug("send_failed", seat=conn.seat, error=str(exc))
            return False


async def _writer_loop(conn: SeatConnection) -> None:
    """Drain one connection's outbox, one frame at a time, in order.

    Exactly one writer per connection, so FIFO per connection is preserved while
    the match driver is never blocked by a slow reader.
    """

    while True:
        text = await conn.outbox.get()
        if text is None:  # shutdown sentinel
            return
        if not await _send_now(conn, text):
            return


def _start_writer(conn: SeatConnection) -> None:
    if conn.writer_task is None:
        conn.writer_task = asyncio.create_task(_writer_loop(conn))


async def _stop_writer(conn: SeatConnection, *, drain_timeout: float = 2.0) -> None:
    """Flush anything still queued, then stop the writer.

    Terminal messages (match_finished / match_aborted) are enqueued like any
    other frame, so the socket must not be closed until the outbox has drained.
    """

    task = conn.writer_task
    if task is None:
        return
    conn.writer_task = None
    try:
        conn.outbox.put_nowait(None)
    except asyncio.QueueFull:
        task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), drain_timeout)
    except (TimeoutError, asyncio.TimeoutError):
        task.cancel()
    except (asyncio.CancelledError, Exception):
        pass


async def _send(conn: SeatConnection, envelope: Any) -> None:
    """Queue one envelope for a single connection.

    Before the writer is running (the hello/welcome handshake) this writes
    inline, so handshake ordering is unchanged. Once the match driver starts,
    sends are queued: a blocked ``send_text`` used to suspend ``run_match``
    itself while the per-turn deadline kept ticking, which aborted matches and
    blamed whichever seat happened to be active.
    """

    text = dumps(envelope)
    if conn.writer_task is None:
        await _send_now(conn, text)
        return
    try:
        conn.outbox.put_nowait(text)
    except asyncio.QueueFull:
        conn.outbox_overflowed = True
        logger.warning(
            "outbox_overflow",
            seat=conn.seat,
            schema_version=1,
            detail="recipient too slow; frame dropped",
        )


async def _send_to_ws(ws: "WebSocket", envelope: Any) -> None:
    """Send one envelope directly to a WebSocket (no SeatConnection lock)."""
    text = dumps(envelope)
    try:
        await ws.send_text(text)
    except Exception as exc:
        logger.debug("send_to_ws_failed", error=str(exc))


async def _shed_overflowed_spectators(conns: "MatchConnections") -> None:
    """Drop spectators that fell behind.

    A spectator is a guest: it never gets to slow a match down. Its writer is
    cancelled rather than drained, because a drain on a stuck socket is exactly
    the block being avoided.
    """

    for spectator in conns.spectators():
        if not spectator.outbox_overflowed:
            continue
        conns.remove_spectator(spectator)
        task = spectator.writer_task
        spectator.writer_task = None
        if task is not None:
            task.cancel()
        try:
            await spectator.websocket.close(code=WS_CLOSE_NORMAL, reason="spectator_too_slow")
        except Exception:
            pass
        logger.warning(
            "spectator_dropped",
            schema_version=1,
            detail="outbox overflow; spectator could not keep up",
        )


async def _broadcast(conns: "MatchConnections", envelope: Any) -> None:
    """Send one envelope to both seats sequentially.

    Sends to seat 0 first, then seat 1.  This ordering must be preserved:
    the Starlette TestClient serialises portal.call across threads; if the
    test drains seat 1 before seat 0, seat 0's message will be delivered on
    the next portal scheduling round, which is fine as long as we do not
    close before that happens.
    """
    for conn in conns:
        await _send(conn, envelope)
    await _shed_overflowed_spectators(conns)


async def _broadcast_match_state(
    conns: "MatchConnections",
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


async def _broadcast_turns_committed(
    conns: "MatchConnections",
    session: MatchSession,
    *,
    since: int,
) -> None:
    """Broadcast one ``turn_committed`` per turn from index ``since`` onward.

    Phase 37: one step can commit several turns — an action followed by the
    chance nodes it leads to, or the chance nodes a match opens with. Sending
    only the last one would drop the action itself.
    """

    local_match = session.local_match
    if local_match is None:
        return
    for turn_index in range(since, len(local_match.turns)):
        await _broadcast(conns, _build_turn_committed_env(session, turn_index))


def _build_turn_committed_env(session: MatchSession, turn_index: int) -> Any:
    local_match = session.local_match
    assert local_match is not None
    turn = local_match.turns[turn_index]
    serializer = session.definition.serializer
    post_snapshot_dict = turn.post_snapshot.model_dump(mode="json")
    # Phase 37: events are load-bearing. They used to be class-name strings in
    # turn_record and an empty list on the body, which was harmless while every
    # game was deterministic — a client could recompute anything it missed. A
    # chance outcome cannot be recomputed, so it has to be on the wire.
    event_payloads = [
        dump_domain_event(event).model_dump(mode="json") for event in turn.events
    ]
    turn_record_dict = {
        "turn_index": turn_index,
        "kind": turn.kind,
        "seat": turn.seat,
        "action": (
            serializer.dump_action(turn.action) if turn.action is not None else None
        ),
        "outcome": (
            dump_chance_outcome(serializer, turn.outcome)
            if turn.kind == TURN_KIND_CHANCE
            else None
        ),
        "events": event_payloads,
        "post_snapshot": post_snapshot_dict,
    }
    body = TurnCommittedBody(
        turn_record=turn_record_dict,
        post_snapshot=post_snapshot_dict,
        events=event_payloads,
    )
    return TurnCommittedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=session.match_id,
        payload=body,
    )


async def _broadcast_match_finished(
    conns: "MatchConnections",
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
    conns: "MatchConnections",
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
    conns: "MatchConnections",
    code: int,
    reason: str,
) -> None:
    """Close both seat WebSockets.

    Seats only: a spectator connection is owned by its own handler, which closes
    it when the match reaches a terminal state.
    """
    for conn in conns.seats():
        # Terminal frames are queued like any other; drain before closing or the
        # client never sees match_finished / match_aborted.
        await _stop_writer(conn)
        try:
            await conn.websocket.close(code=code, reason=reason)
        except Exception:
            pass


async def _safe_receive_text(ws: "WebSocket") -> str | None:
    """Receive one text frame; return None on any error (disconnect, close, etc.)."""
    try:
        return await ws.receive_text()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Heartbeat loop
# ---------------------------------------------------------------------------


async def _heartbeat_loop(
    conn: SeatConnection,
    match_id: str,
    interval_s: float,
    max_misses: int,
) -> None:
    """Ping conn every interval_s; close with 4408 after max_misses consecutive missed pongs."""
    while True:
        await asyncio.sleep(interval_s)
        nonce = str(uuid.uuid4())[:8]
        conn.pending_pong_nonce = nonce
        conn.pong_event.clear()
        ping_env = PingEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            match_id=match_id,
            payload=PingBody(nonce=nonce),
        )
        await _send(conn, ping_env)
        try:
            await asyncio.wait_for(conn.pong_event.wait(), timeout=interval_s)
            conn.consecutive_heartbeat_misses = 0
        except asyncio.TimeoutError:
            conn.consecutive_heartbeat_misses += 1
            if conn.consecutive_heartbeat_misses >= max_misses:
                conn.heartbeat_timed_out = True
                try:
                    await conn.websocket.close(
                        code=HEARTBEAT_CLOSE_CODE, reason="heartbeat_timeout"
                    )
                except Exception:
                    pass
                return


# ---------------------------------------------------------------------------
# Idle receive loop (for the off-turn seat)
# ---------------------------------------------------------------------------


async def _idle_receive_loop(
    conn: SeatConnection,
    done_event: asyncio.Event,
) -> None:
    """Drain WS frames from an off-turn seat: handle pong, detect disconnect."""
    while not done_event.is_set():
        recv_task = asyncio.create_task(_safe_receive_text(conn.websocket))
        done_task = asyncio.create_task(done_event.wait())
        done_set, pending = await asyncio.wait(
            {recv_task, done_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        if recv_task in done_set and not recv_task.cancelled():
            raw = recv_task.result()
            if raw is None:
                # WebSocket closed (normal or abnormal disconnect).
                conn.heartbeat_timed_out = False  # flag only for active-seat path
                return
            try:
                env = loads(raw)
                if env.type == "pong":
                    nonce = getattr(env.payload, "nonce", None)
                    if nonce == conn.pending_pong_nonce:
                        conn.pong_event.set()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Receive action (active seat)
# ---------------------------------------------------------------------------

_DEADLINE_EXPIRED = "deadline_expired"


async def _receive_one_text(ws: "WebSocket") -> str | None:
    """Receive exactly one text frame; return None on disconnect/error."""
    try:
        return await ws.receive_text()
    except Exception:
        return None


async def _receive_action(
    active_conn: SeatConnection,
    match_id: str,
    committed_turn_ids: set[str],
    rejected_turn_ids: set[str],
    *,
    deadline_event: asyncio.Event | None = None,
    limiter: Any = None,
) -> tuple[str | None, ActionResponsePayload | None, str | None]:
    """Wait for a valid action_response frame from the active seat.

    Returns (turn_id, payload, error_msg).  error_msg non-None → send error back.
    Returns (None, None, "disconnected") on WS close.
    Returns (None, None, "deadline_expired") when deadline_event fires.
    Duplicate turn_ids are silently dropped — returns (None, None, None) meaning retry.
    Pong frames update the heartbeat state and are consumed silently.

    Protocol §13: a seat exceeding the per-match action rate has its connection
    closed with 4429.  The next receive then fails naturally and the existing
    disconnect-grace path takes over, so no new abort reason is needed.

    Deadline enforcement uses asyncio.wait on a per-receive task so that
    receive_text() is never cancelled mid-call (which can corrupt ASGI state).
    Instead, when the deadline fires, this function returns immediately and the
    caller closes the WebSocket, causing the next receive_text() (if any) to fail
    naturally.
    """
    while True:
        # Start one receive_text() as a task so we can race it against the deadline.
        recv_task = asyncio.create_task(_receive_one_text(active_conn.websocket))

        if deadline_event is not None and not deadline_event.is_set():
            deadline_task = asyncio.create_task(deadline_event.wait())
            done_set, pending = await asyncio.wait(
                {recv_task, deadline_task}, return_when=asyncio.FIRST_COMPLETED
            )
            # Cancel whichever task didn't fire.
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            if deadline_task in done_set and recv_task not in done_set:
                # Deadline fired before we got a frame — return deadline_expired.
                # recv_task is cancelled; the WS is NOT closed here (caller does that).
                return None, None, _DEADLINE_EXPIRED

            if recv_task not in done_set:
                # recv_task was cancelled (shouldn't happen, but guard defensively).
                return None, None, _DEADLINE_EXPIRED
        else:
            # No deadline — just await the receive directly.
            await recv_task

        try:
            raw = recv_task.result()
        except Exception:
            return None, None, "disconnected"

        if raw is None:
            return None, None, "disconnected"

        try:
            envelope = loads(raw)
        except WireProtocolError as exc:
            return None, None, str(exc)

        if envelope.type != "action_response":
            if envelope.type == "pong":
                nonce = getattr(envelope.payload, "nonce", None)
                if nonce == active_conn.pending_pong_nonce:
                    active_conn.pong_event.set()
                continue
            if envelope.type not in ("ping",):
                return None, None, f"expected action_response, got {envelope.type!r}"
            continue

        if limiter is not None:
            try:
                limiter.check_action(match_id=match_id)
            except RateLimitExceeded as exc:
                logger.warning(
                    "rate_limited",
                    match_id=match_id,
                    seat=active_conn.seat,
                    schema_version=1,
                    scope=exc.scope,
                    detail=exc.message,
                )
                try:
                    await active_conn.websocket.close(
                        code=CLOSE_RATE_LIMITED, reason=exc.scope
                    )
                except Exception:
                    pass
                return None, None, "disconnected"

        turn_id = envelope.turn_id or str(uuid.uuid4())

        if turn_id in committed_turn_ids or turn_id in rejected_turn_ids:
            logger.debug("duplicate_turn_id_dropped", turn_id=turn_id, match_id=match_id)
            continue

        return turn_id, envelope.payload.action_response, None


# ---------------------------------------------------------------------------
# Deadline timer helpers
# ---------------------------------------------------------------------------


async def _deadline_sleep(event: asyncio.Event, delay_s: float) -> None:
    """Sleep delay_s then set event (for per-turn deadline signalling)."""
    await asyncio.sleep(delay_s)
    event.set()


def _cancel_task(task: "asyncio.Task | None") -> None:
    """Cancel a task if it is not None and not already done."""
    if task is not None and not task.done():
        task.cancel()


# ---------------------------------------------------------------------------
# App-state accessors for reconnect (Phase 32)
# ---------------------------------------------------------------------------


def _get_reconnect_events(app_state: Any) -> dict[str, dict[int, asyncio.Event]]:
    if not hasattr(app_state, "_ws_reconnect_events"):
        app_state._ws_reconnect_events = {}
    return app_state._ws_reconnect_events


def _get_reconnect_conns(app_state: Any) -> dict[str, dict[int, SeatConnection]]:
    if not hasattr(app_state, "_ws_reconnect_conns"):
        app_state._ws_reconnect_conns = {}
    return app_state._ws_reconnect_conns


# ---------------------------------------------------------------------------
# Main match driver
# ---------------------------------------------------------------------------


async def run_match(
    match: "Match",
    conns: "MatchConnections",
    *,
    done_event: asyncio.Event,
    app_state: Any,
    heartbeat_interval_s: float = 20.0,
    heartbeat_max_misses: int = 2,
) -> None:
    """Drive a match to completion over two WebSocket connections.

    Must be called only after both seats have completed the hello/welcome handshake.
    Mutates match.session on each turn (Match is a mutable dataclass).

    Parameters
    ----------
    match:
        The server-layer Match record.
    conns:
        (conn_seat0, conn_seat1) SeatConnection tuple.
    done_event:
        Set by the caller's finally block when run_match returns; also waited on
        by idle handlers and reconnect handlers.
    app_state:
        FastAPI app.state; used to look up reconnect events and connection slots.
    heartbeat_interval_s:
        Seconds between heartbeat pings.
    heartbeat_max_misses:
        Consecutive missed pongs before closing with 4408.
    """
    arena = match.arena
    session = match.session

    session = arena.start_session(session)
    match.session = session
    logger.info(
        "match_started",
        match_id=session.match_id,
        seat=None,
        schema_version=1,
        game_id=match.game_id,
    )

    # One heartbeat task at a time — only for the ACTIVE seat during its turn.
    # Off-turn seats are not pinged: their disconnect is detected when their turn arrives.
    # This avoids concurrent receive_text() calls that would race with _receive_action.
    hb_task: asyncio.Task | None = None

    def _start_hb(conn: SeatConnection) -> asyncio.Task:
        conn.heartbeat_timed_out = False
        conn.consecutive_heartbeat_misses = 0
        return asyncio.create_task(
            _heartbeat_loop(conn, match.match_id, heartbeat_interval_s, heartbeat_max_misses)
        )

    async def _cancel_hb() -> None:
        nonlocal hb_task
        if hb_task is not None:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
            hb_task = None

    # One writer task per seat for the life of the match: the driver enqueues and
    # never blocks on a socket.
    for _seat_conn in conns.seats():
        _start_writer(_seat_conn)

    try:
        if session.lifecycle is RuntimeLifecycle.ABORTED:
            await _broadcast_match_state(conns, session)
            await _broadcast_match_aborted(conns, session)
            await _close_both(conns, WS_CLOSE_NORMAL, "match_aborted")
            return

        # A game that opens at a chance node — a deal, an opening roll — has
        # committed turns before any seat acts; their outcomes go out first.
        await _broadcast_turns_committed(conns, session, since=0)
        await _broadcast_match_state(conns, session)

        committed_turn_ids: set[str] = set()
        rejected_turn_ids: set[str] = set()

        deadline_s = (
            match.per_turn_deadline_ms / 1000.0 if match.per_turn_deadline_ms > 0 else None
        )

        while session.lifecycle is RuntimeLifecycle.RUNNING:
            local_match = session.local_match
            assert local_match is not None

            if local_match.rules_engine.is_terminal(local_match.state):
                break

            active_seat = local_match.rules_engine.current_seat(local_match.state)
            active_conn = conns[active_seat]
            # One accepted action may commit several turns (Phase 37 chance
            # nodes); everything from here on is broadcast once it lands.
            turns_before = len(local_match.turns)

            # Start heartbeat only for this turn's active seat.
            await _cancel_hb()
            hb_task = _start_hb(active_conn)

            obs_request = build_observation_request(local_match)
            obs_body = ObservationRequestBody(
                observation_request=obs_request,
                deadline_ms=match.per_turn_deadline_ms,
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

            # Per-turn deadline: create a fresh Event + timer task per observation.
            # The event is passed into _receive_action so it can return without
            # cancelling receive_text() (which corrupts ASGI state in some WS impls).
            deadline_event: asyncio.Event | None = None
            deadline_timer_task: asyncio.Task | None = None
            if deadline_s:
                deadline_event = asyncio.Event()
                deadline_timer_task = asyncio.create_task(
                    _deadline_sleep(deadline_event, deadline_s)
                )

            while not action_accepted:
                turn_id, action_resp, error_msg = await _receive_action(
                    active_conn,
                    session.match_id,
                    committed_turn_ids,
                    rejected_turn_ids,
                    deadline_event=deadline_event,
                    limiter=getattr(app_state, "rate_limiter", None),
                )

                # --- Per-turn deadline expired ---
                if error_msg == _DEADLINE_EXPIRED:
                    _cancel_task(deadline_timer_task)
                    logger.warning(
                        "turn_deadline_expired",
                        match_id=session.match_id,
                        seat=active_seat,
                        schema_version=1,
                    )
                    session = arena.abort_session(
                        session,
                        reason=AbortReason.TURN_DEADLINE_EXPIRED,
                        message="Per-turn deadline expired.",
                    )
                    match.session = session
                    await _broadcast_match_state(conns, session)
                    await _broadcast_match_aborted(conns, session)
                    logger.info(
                        "match_aborted",
                        match_id=session.match_id,
                        seat=active_seat,
                        schema_version=1,
                        reason="turn_deadline_expired",
                    )
                    await _close_both(conns, WS_CLOSE_NORMAL, "turn_deadline_expired")
                    return

                # --- Disconnect handling ---
                if error_msg == "disconnected":
                    if active_conn.heartbeat_timed_out:
                        # Heartbeat loop already closed the active seat's WS with 4408.
                        _cancel_task(deadline_timer_task)
                        await _cancel_hb()
                        logger.warning(
                            "heartbeat_timeout",
                            match_id=session.match_id,
                            seat=active_seat,
                            schema_version=1,
                        )
                        session = arena.abort_session(
                            session,
                            reason=AbortReason.HEARTBEAT_TIMEOUT,
                            message="Heartbeat timeout.",
                        )
                        match.session = session
                        await _broadcast_match_state(conns, session)
                        await _broadcast_match_aborted(conns, session)
                        logger.info(
                            "match_aborted",
                            match_id=session.match_id,
                            seat=active_seat,
                            schema_version=1,
                            reason="heartbeat_timeout",
                        )
                        await _close_both(conns, WS_CLOSE_NORMAL, "heartbeat_timeout")
                        return

                    # Normal disconnect: pause deadline, wait up to grace_ms for reconnect.
                    _cancel_task(deadline_timer_task)
                    deadline_event = None
                    deadline_timer_task = None

                    grace_s = match.disconnect_grace_ms / 1000.0
                    reconnect_events = _get_reconnect_events(app_state)
                    reconnect_event = (
                        reconnect_events.get(match.match_id, {}).get(active_seat)
                    )
                    logger.info(
                        "seat_disconnected",
                        match_id=match.match_id,
                        seat=active_seat,
                        schema_version=1,
                        grace_ms=match.disconnect_grace_ms,
                    )

                    if reconnect_event is None:
                        # No event registered (shouldn't happen); abort immediately.
                        session = arena.abort_session(
                            session,
                            reason=AbortReason.PEER_DISCONNECTED,
                            message="Seat disconnected and did not reconnect within grace period.",
                        )
                        match.session = session
                        await _broadcast_match_state(conns, session)
                        await _broadcast_match_aborted(conns, session)
                        logger.info(
                            "match_aborted",
                            match_id=session.match_id,
                            seat=active_seat,
                            schema_version=1,
                            reason="peer_disconnected",
                        )
                        await _close_both(conns, WS_CLOSE_NORMAL, "peer_disconnected")
                        return

                    reconnect_event.clear()
                    logger.debug(
                        "seat_disconnected_awaiting_reconnect",
                        match_id=match.match_id,
                        seat=active_seat,
                        grace_s=grace_s,
                        schema_version=1,
                    )
                    try:
                        await asyncio.wait_for(reconnect_event.wait(), timeout=grace_s)
                    except asyncio.TimeoutError:
                        session = arena.abort_session(
                            session,
                            reason=AbortReason.PEER_DISCONNECTED,
                            message="Seat disconnected and did not reconnect within grace period.",
                        )
                        match.session = session
                        await _broadcast_match_state(conns, session)
                        await _broadcast_match_aborted(conns, session)
                        logger.info(
                            "match_aborted",
                            match_id=session.match_id,
                            seat=active_seat,
                            schema_version=1,
                            reason="peer_disconnected_grace_expired",
                        )
                        await _close_both(conns, WS_CLOSE_NORMAL, "peer_disconnected")
                        return

                    # Reconnected: swap in the new SeatConnection.
                    new_conn = (
                        _get_reconnect_conns(app_state)
                        .get(match.match_id, {})
                        .get(active_seat)
                    )
                    if new_conn is None:
                        session = arena.abort_session(
                            session,
                            reason=AbortReason.PEER_DISCONNECTED,
                            message="Reconnect event set but no new connection found.",
                        )
                        match.session = session
                        await _broadcast_match_state(conns, session)
                        await _broadcast_match_aborted(conns, session)
                        logger.info(
                            "match_aborted",
                            match_id=session.match_id,
                            seat=active_seat,
                            schema_version=1,
                            reason="peer_disconnected_no_conn",
                        )
                        await _close_both(conns, WS_CLOSE_NORMAL, "peer_disconnected")
                        return

                    conns.replace_seat(active_seat, new_conn)
                    active_conn = new_conn

                    # Replace heartbeat task for the reconnected seat.
                    await _cancel_hb()
                    hb_task = _start_hb(new_conn)

                    # Re-send observation request with a fresh deadline budget.
                    if deadline_s:
                        deadline_event = asyncio.Event()
                        deadline_timer_task = asyncio.create_task(
                            _deadline_sleep(deadline_event, deadline_s)
                        )
                    await _send(active_conn, obs_env)
                    continue  # back to the while not action_accepted loop

                # --- Non-fatal parse/protocol error ---
                if error_msg is not None:
                    logger.warning(
                        "protocol_violation",
                        match_id=session.match_id,
                        seat=active_seat,
                        schema_version=1,
                        detail=error_msg,
                    )
                    err_env = ErrorEnvelope(
                        schema_version=WIRE_SCHEMA_VERSION,
                        match_id=session.match_id,
                        payload=ErrorBody(code="malformed_envelope", message=error_msg),
                    )
                    await _send(active_conn, err_env)
                    continue

                # --- Idempotency: duplicate turn_id silently dropped ---
                if turn_id is None and action_resp is None and error_msg is None:
                    # _receive_action returns (None, None, None) for duplicates.
                    continue

                assert turn_id is not None
                assert action_resp is not None

                try:
                    typed_action = load_action_response(session.definition, action_resp)
                    next_match = apply_match_action(local_match, active_seat, typed_action)
                except ArenaCoreError as exc:
                    domain_err = dump_domain_error(exc)
                    rejected_turn_ids.add(turn_id)
                    logger.warning(
                        "action_rejected",
                        match_id=session.match_id,
                        seat=active_seat,
                        schema_version=1,
                        turn_id=turn_id,
                        error_code=domain_err.code,
                        retries_remaining=retries_left - 1 if retries_left > 0 else 0,
                    )

                    if retries_left == 0:
                        # §8.6: rejected(0) → match_state(aborted) → match_aborted → close
                        rej_env = _make_rejected_env(
                            session, active_seat, turn_id, domain_err, 0
                        )
                        await _send(active_conn, rej_env)
                        session = arena.abort_session(
                            session,
                            reason=AbortReason.ADAPTER_ERROR,
                            message="Retry budget exhausted.",
                        )
                        match.session = session
                        await _broadcast_match_state(conns, session)
                        await _broadcast_match_aborted(conns, session)
                        logger.info(
                            "match_aborted",
                            match_id=session.match_id,
                            seat=active_seat,
                            schema_version=1,
                            reason="adapter_error_budget_exhausted",
                        )
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
                    logger.warning(
                        "action_rejected",
                        match_id=session.match_id,
                        seat=active_seat,
                        schema_version=1,
                        turn_id=turn_id,
                        error_code=domain_err.code,
                        retries_remaining=retries_left - 1 if retries_left > 0 else 0,
                    )

                    if retries_left == 0:
                        rej_env = _make_rejected_env(
                            session, active_seat, turn_id, domain_err, 0
                        )
                        await _send(active_conn, rej_env)
                        session = arena.abort_session(
                            session,
                            reason=AbortReason.ADAPTER_ERROR,
                            message="Retry budget exhausted.",
                        )
                        match.session = session
                        await _broadcast_match_state(conns, session)
                        await _broadcast_match_aborted(conns, session)
                        logger.info(
                            "match_aborted",
                            match_id=session.match_id,
                            seat=active_seat,
                            schema_version=1,
                            reason="adapter_error_budget_exhausted",
                        )
                        await _close_both(conns, WS_CLOSE_NORMAL, "adapter_error")
                        return

                    retries_left -= 1
                    rej_env = _make_rejected_env(
                        session, active_seat, turn_id, domain_err, retries_left
                    )
                    await _send(active_conn, rej_env)
                    continue

                # Action accepted.
                _cancel_task(deadline_timer_task)
                committed_turn_ids.add(turn_id)
                action_accepted = True

                new_events = session.events + (
                    TurnAccepted(
                        match_id=session.match_id,
                        seat=active_seat,
                        turn_index=turns_before + 1,
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

                logger.info(
                    "turn_committed",
                    match_id=session.match_id,
                    seat=active_seat,
                    schema_version=1,
                    turn_index=turns_before,
                    turn_id=turn_id,
                )
                await _broadcast_turns_committed(conns, session, since=turns_before)
                await _broadcast_match_state(conns, session)

        # Match reached terminal state.
        if session.lifecycle is RuntimeLifecycle.FINISHED:
            logger.info(
                "match_finished",
                match_id=session.match_id,
                seat=None,
                schema_version=1,
            )
            await _broadcast_match_finished(conns, session)
        else:
            logger.info(
                "match_aborted",
                match_id=session.match_id,
                seat=None,
                schema_version=1,
                reason=session.abort.reason.value if session.abort else "unknown",
            )
            await _broadcast_match_aborted(conns, session)

        await _close_both(conns, WS_CLOSE_NORMAL, "normal_closure")

    finally:
        # Cancel heartbeat task on any exit path.
        # (deadline_timer_task is cancelled inline at each return point via _cancel_task.)
        await _cancel_hb()
        # Flush and stop writers on every exit path, including the ones that
        # return without calling _close_both.
        for _seat_conn in conns.seats():
            await _stop_writer(_seat_conn)


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
    """Send a welcome envelope to one seat after a successful hello handshake.

    Generates and stores a fresh resume_token in match.resume_tokens[seat].
    The token rotates on every call (initial connect and every reconnect).
    """
    players = _build_player_info(match)
    match_config_dict = match.definition.serializer.dump_config(match.match_config)

    token = _make_resume_token()
    match.resume_tokens[conn.seat] = token  # store for reconnect validation

    body = WelcomeBody(
        match_id=match.match_id,
        game_id=match.game_id,
        game_schema_version=1,
        seat=conn.seat,
        lifecycle=match.session.lifecycle.value,
        schema_version=WIRE_SCHEMA_VERSION,
        negotiated_schema_version=WIRE_SCHEMA_VERSION,
        resume_token=token,
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
