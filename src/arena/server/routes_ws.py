"""FastAPI WebSocket routes for arena.server.

WS /matches/{match_id}/play?seat={0|1}  -- primary play channel (§4)
WS /matches/{match_id}/spectate          -- read-only spectator channel (§4)
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket

from arena.adapters.websocket import (
    WIRE_SCHEMA_VERSION,
    ErrorEnvelope,
    MatchStateEnvelope,
    loads,
)
from arena.adapters.websocket.errors import SchemaVersionMismatch, WireProtocolError
from arena.adapters.websocket.messages import ErrorBody
from arena.server.config import HEARTBEAT_MAX_MISSES
from arena.server.errors import MatchNotFound
from arena.server.rate_limits import (
    CLOSE_RATE_LIMITED,
    RateLimiter,
    RateLimitExceeded,
    client_address,
)
from arena.server.registry import Match, MatchRegistry
from arena.server.runtime_bridge import (
    WS_CLOSE_NORMAL,
    MatchConnections,
    SeatConnection,
    SpectatorConnection,
    _get_match_conns,
    _get_pending_spectators,
    _get_reconnect_conns,
    _get_reconnect_events,
    _send,
    _start_writer,
    _stop_writer,
    receive_text_frame,
    run_match,
    send_spectator_welcome,
    send_welcome,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── Close codes (protocol §9) ──────────────────────────────────────────────
_CLOSE_SCHEMA_MISMATCH = 4400
_CLOSE_UNAUTHORIZED = 4401
_CLOSE_UNSUPPORTED_ENDPOINT = 4404
_CLOSE_SEAT_TAKEN = 4409
_CLOSE_MATCH_NOT_FOUND = 4410
_CLOSE_MALFORMED = 4422
_CLOSE_RATE_LIMITED = CLOSE_RATE_LIMITED
_CLOSE_SERVER_ERROR = 4500


# ── Per-match seat-slot tracking ──────────────────────────────────────────
# match_id → {seat: SeatConnection | None}
# Accessed only from async handlers (single-threaded event loop); no lock needed.

def _get_seat_slots(app_state: Any) -> dict[str, dict[int, SeatConnection | None]]:
    if not hasattr(app_state, "_ws_seat_slots"):
        app_state._ws_seat_slots = {}
    return app_state._ws_seat_slots


def _release_slot(app_state: Any, match_id: str, seat: int, conn: SeatConnection) -> None:
    """Free ``seat`` if ``conn`` still holds it.

    Never re-creates an evicted match's entry: indexing it after eviction used
    to bring the per-match dict back, and leak it.
    """

    slots = _get_seat_slots(app_state).get(match_id)
    if slots is not None and slots.get(seat) is conn:
        slots[seat] = None


def _get_ready_events(app_state: Any) -> dict[str, asyncio.Event]:
    """Per-match asyncio.Event set when both seats have sent hello and received welcome."""
    if not hasattr(app_state, "_ws_ready_events"):
        app_state._ws_ready_events = {}
    return app_state._ws_ready_events


def _get_done_events(app_state: Any) -> dict[str, asyncio.Event]:
    """Per-match asyncio.Event set when run_match has finished (match over)."""
    if not hasattr(app_state, "_ws_done_events"):
        app_state._ws_done_events = {}
    return app_state._ws_done_events


async def _close(ws: WebSocket, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except Exception:
        pass


def _client_ip(ws: WebSocket) -> str:
    """Source address for rate-limit bucketing (protocol §13); see ``client_address``."""

    client = ws.client
    return client_address(
        ws.headers,
        client.host if client is not None else None,
        getattr(ws.app.state, "client_ip_header", None),
    )


@router.websocket("/matches/{match_id}/play")
async def play_handler(ws: WebSocket, match_id: str, seat: int = -1) -> None:
    """Primary play channel (protocol §5/§8/§10).

    Thin wrapper holding a protocol §13 connection slot for the lifetime of the
    session, so every early return inside ``_play_session`` still releases it.
    """

    limiter: RateLimiter | None = getattr(ws.app.state, "rate_limiter", None)
    if limiter is None:
        await _play_session(ws, match_id, seat)
        return

    ip = _client_ip(ws)
    try:
        limiter.acquire_connection(ip=ip, match_id=match_id)
    except RateLimitExceeded as exc:
        logger.warning(
            "rate_limited",
            match_id=match_id,
            seat=seat,
            schema_version=1,
            scope=exc.scope,
            detail=exc.message,
        )
        await ws.accept()
        await _close(ws, _CLOSE_RATE_LIMITED, exc.scope)
        return

    try:
        await _play_session(ws, match_id, seat)
    finally:
        limiter.release_connection(ip=ip, match_id=match_id)


async def _play_session(ws: WebSocket, match_id: str, seat: int = -1) -> None:
    """Drive one play-channel session; see :func:`play_handler`."""

    # 1. Look up match.
    registry: MatchRegistry = ws.app.state.match_registry
    try:
        match: Match = registry.get(match_id)
    except MatchNotFound:
        await ws.accept()
        await _close(ws, _CLOSE_MATCH_NOT_FOUND, "match_not_found")
        return

    # 2. Validate seat param.
    if seat not in (0, 1):
        await ws.accept()
        await _close(ws, _CLOSE_MALFORMED, "invalid_seat")
        return

    # 3. Accept the WebSocket.
    await ws.accept()

    # 4. Receive the first frame; expect a hello envelope.
    raw = await receive_text_frame(ws)
    if raw is None:  # gone, or a binary frame (already closed 1003)
        await _close(ws, _CLOSE_MALFORMED, "no_hello_received")
        return

    try:
        envelope = loads(raw)
    except SchemaVersionMismatch:
        logger.warning(
            "protocol_violation",
            match_id=match_id,
            seat=seat,
            schema_version=1,
            detail="schema_version_mismatch",
        )
        await _close(ws, _CLOSE_SCHEMA_MISMATCH, "schema_version_mismatch")
        return
    except WireProtocolError:
        logger.warning(
            "protocol_violation",
            match_id=match_id,
            seat=seat,
            schema_version=1,
            detail="malformed_envelope",
        )
        await _close(ws, _CLOSE_MALFORMED, "malformed_envelope")
        return

    if envelope.type != "hello":
        logger.warning(
            "protocol_violation",
            match_id=match_id,
            seat=seat,
            schema_version=1,
            detail=f"expected_hello_got_{envelope.type}",
        )
        await _close(ws, _CLOSE_MALFORMED, f"expected_hello_got_{envelope.type}")
        return

    hello = envelope.payload
    app_state = ws.app.state

    # 4a. Phase 32: check for reconnect (resume_token present in hello).
    if hello.resume_token is not None:
        await _handle_reconnect(
            ws,
            seat,
            match_id,
            match,
            hello.resume_token,
            app_state,
            hello.supported_schema_versions,
        )
        return

    # 4b. Phase 38: once a match's driver has ended, no seat can be claimed. The
    # finished match stays in the registry for late transcript reads, and its
    # seats are released, so without this anyone holding the match id (every
    # spectator) could take a seat and read that seat's private transcript.
    if _match_closed(match, app_state):
        await _close(ws, _CLOSE_MATCH_NOT_FOUND, "match_over")
        return

    # 4c. Once the match is running, a seat is reachable only by its resume
    # token. A seat slot can be empty mid-match (its socket dropped and the
    # grace period is running), and a fresh hello used to claim it there: the
    # claimant was welcomed with a new token, resumed, and read the seat's
    # private transcript while the real player was locked out.
    if _get_match_conns(app_state).get(match_id) is not None:
        await _close(ws, _CLOSE_SEAT_TAKEN, "seat_taken")
        return

    # 5. Validate requested_seat matches the URL ?seat= param.
    if hello.requested_seat != seat:
        await _close(ws, _CLOSE_MALFORMED, "seat_mismatch")
        return

    # 6. Schema-version negotiation: the client must read the version we emit.
    if WIRE_SCHEMA_VERSION not in hello.supported_schema_versions:
        await _close(ws, _CLOSE_SCHEMA_MISMATCH, "schema_version_mismatch")
        return

    # 7. Check seat occupancy.
    seat_slots = _get_seat_slots(app_state)
    if match_id not in seat_slots:
        seat_slots[match_id] = {0: None, 1: None}

    if seat_slots[match_id].get(seat) is not None:
        await _close(ws, _CLOSE_SEAT_TAKEN, "seat_taken")
        return

    # 8. Register the connection and send welcome.
    conn = SeatConnection(websocket=ws, seat=seat)
    seat_slots[match_id][seat] = conn

    try:
        await send_welcome(conn, match)
    except Exception as exc:
        logger.warning(
            "welcome_send_failed",
            match_id=match_id,
            seat=seat,
            schema_version=1,
            error=str(exc),
        )
        _release_slot(app_state, match_id, seat, conn)
        await _close(ws, _CLOSE_SERVER_ERROR, "server_error")
        return

    logger.info(
        "seat_connected",
        match_id=match_id,
        seat=seat,
        schema_version=1,
    )

    # 9. Initialise per-match ready / done / reconnect event dicts.
    ready_events = _get_ready_events(app_state)
    if match_id not in ready_events:
        ready_events[match_id] = asyncio.Event()
    ready_event = ready_events[match_id]

    done_events = _get_done_events(app_state)
    if match_id not in done_events:
        done_events[match_id] = asyncio.Event()
    done_event = done_events[match_id]

    # Phase 32: pre-create reconnect event for this seat so run_match can find it.
    # setdefault: never replace an Event the driver may already be waiting on.
    reconnect_events = _get_reconnect_events(app_state)
    reconnect_events.setdefault(match_id, {}).setdefault(seat, asyncio.Event())

    other_seat = 1 - seat
    if seat_slots[match_id].get(other_seat) is not None:
        # Both seats present; second-arriving seat fires the event.
        ready_event.set()
    else:
        # First-arriving seat: wait for the event, draining receives to detect disconnect.
        while not ready_event.is_set():
            recv_task = asyncio.create_task(_safe_receive_text(ws))
            wait_task = asyncio.create_task(ready_event.wait())
            done, pending = await asyncio.wait(
                {recv_task, wait_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

            if recv_task in done and not recv_task.cancelled():
                result = recv_task.result()
                if result is None and ready_event.is_set():
                    # Closed in the same instant the opponent arrived: the
                    # match has already taken this connection. Keep the slot so
                    # nobody else can claim the seat; the driver sees the
                    # disconnect and runs the normal grace path.
                    break
                if result is None:
                    # WebSocket closed before second seat arrived.
                    _release_slot(app_state, match_id, seat, conn)
                    logger.info(
                        "seat_disconnected",
                        match_id=match_id,
                        seat=seat,
                        schema_version=1,
                        detail="disconnected_before_match_start",
                    )
                    return
                # Received some unexpected frame while idle; discard (match not started).

    # 10. Both seats are connected.  Seat 1's handler drives run_match; seat 0 just waits
    #     for the done_event (set by run_match when the match ends and both WS are closed).
    if seat == 1:
        conn0 = seat_slots[match_id][0]
        conn1 = seat_slots[match_id][1]
        assert conn0 is not None
        assert conn1 is not None
        conns = MatchConnections(conn0, conn1)
        _get_match_conns(app_state)[match_id] = conns

        # Spectators that attached before both seats arrived parked in the
        # pending list; fold them in now so they receive the opening broadcasts.
        for pending_spectator in _get_pending_spectators(app_state).pop(match_id, []):
            conns.add_spectator(pending_spectator)

        try:
            await run_match(
                match,
                conns,
                done_event=done_event,
                app_state=app_state,
                heartbeat_interval_s=app_state.heartbeat_interval_ms / 1000.0,
                heartbeat_max_misses=getattr(
                    app_state, "heartbeat_max_misses", HEARTBEAT_MAX_MISSES
                ),
            )
        except Exception as exc:
            logger.exception(
                "run_match_error",
                match_id=match_id,
                seat=seat,
                schema_version=1,
                error=str(exc),
            )
        finally:
            done_event.set()
            # A resume token must not outlive the match it resumes (Phase 38).
            match.resume_tokens.clear()
            if match_id in seat_slots:  # absent once the match is evicted
                seat_slots[match_id] = {0: None, 1: None}
            _get_match_conns(app_state).pop(match_id, None)
            _get_pending_spectators(app_state).pop(match_id, None)
    else:
        # Seat 0: wait until run_match signals it's done.
        # Do NOT call receive_text here — run_match receives from ws0 when it's seat 0's turn.
        try:
            await _wait_done_or_superseded(done_event, conn)
        except Exception:
            pass
        finally:
            _release_slot(app_state, match_id, seat, conn)


# ---------------------------------------------------------------------------
# Reconnect handler (Phase 32)
# ---------------------------------------------------------------------------


async def _handle_reconnect(
    ws: WebSocket,
    seat: int,
    match_id: str,
    match: Match,
    resume_token: str,
    app_state: Any,
    supported_schema_versions: list[int],
) -> None:
    """Handle a reconnecting client presenting a valid resume_token.

    Phase 38: the new connection takes over the seat's broadcast slot in the same
    uninterrupted step that builds its replay transcript. Every turn committed
    before the swap is in ``welcome.transcript``, and every turn after it arrives
    live, with no gap and no duplicate. That also makes an off-turn reconnect
    work: the seat is swapped in straight away rather than when its turn comes.
    """

    if _match_closed(match, app_state):
        await _close(ws, _CLOSE_MATCH_NOT_FOUND, "match_over")
        return

    # Validate token. Section 11: a token bound to another seat is a 4401; one
    # that is simply stale (rotated, or from before a restart) a 4410.
    expected = match.resume_tokens.get(seat)
    if expected is None or not secrets.compare_digest(expected, resume_token):
        other = match.resume_tokens.get(1 - seat)
        if other is not None and secrets.compare_digest(other, resume_token):
            await _close(ws, _CLOSE_UNAUTHORIZED, "unauthorized")
        else:
            await _close(ws, _CLOSE_MATCH_NOT_FOUND, "invalid_resume_token")
        return

    # A reconnecting client negotiates like a new one: it will be sent a
    # transcript in the current wire shape.
    if WIRE_SCHEMA_VERSION not in supported_schema_versions:
        await _close(ws, _CLOSE_SCHEMA_MISMATCH, "schema_version_mismatch")
        return

    # Build new SeatConnection and send welcome.
    # send_welcome rotates the resume_token in match.resume_tokens[seat] atomically.
    # Phase 38: the welcome carries the seat's own transcript so far (§11), so a
    # reconnecting client recovers everything it missed and nothing more.
    from arena.server.runtime_bridge import (
        _build_match_state_body,
        _send,
        _start_writer,
        _stop_writer,
    )

    live = _get_match_conns(app_state).get(match_id)
    if live is None:
        # The match has not started. There is nothing to resume: a client whose
        # socket dropped while waiting for its opponent says a fresh hello.
        await _close(ws, _CLOSE_SEAT_TAKEN, "match_not_started")
        return

    new_conn = SeatConnection(websocket=ws, seat=seat)
    # With its writer running, every send below only queues: nothing from here
    # to replace_seat yields to the event loop, so no turn can commit between
    # the transcript being built and the connection joining the broadcast.
    _start_writer(new_conn)
    try:
        await send_welcome(new_conn, match, with_transcript=True)
    except Exception:
        await _stop_writer(new_conn)
        await _close(ws, _CLOSE_SERVER_ERROR, "server_error")
        return

    # Send current match_state so the client knows the lifecycle.
    await _send(
        new_conn,
        MatchStateEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            match_id=match_id,
            payload=_build_match_state_body(match.session),
        ),
    )

    old_conn = live[seat]
    live.replace_seat(seat, new_conn)
    # The slot follows the seat's live connection. Left pointing at the old one,
    # the old handler's exit cleared it, and the seat looked free mid-match.
    seat_slots = _get_seat_slots(app_state).get(match_id)
    if seat_slots is not None:
        seat_slots[seat] = new_conn
    # The old socket may still be open (a half-open TCP session is exactly what
    # resume tokens are for). Close it: if this seat is the active one, the
    # driver is waiting on that socket, and closing it hands the turn to the
    # new connection through the normal disconnect path.
    if old_conn is not new_conn:
        try:
            await old_conn.websocket.close(code=WS_CLOSE_NORMAL, reason="superseded")
        except Exception:
            pass

    # Register new connection so run_match can pick it up.
    reconnect_conns = _get_reconnect_conns(app_state)
    reconnect_conns.setdefault(match_id, {})[seat] = new_conn

    # Signal run_match that the seat has reconnected.
    reconnect_events = _get_reconnect_events(app_state)
    event = reconnect_events.get(match_id, {}).get(seat)
    if event:
        event.set()

    logger.info(
        "seat_connected",
        match_id=match_id,
        seat=seat,
        schema_version=1,
        reconnect=True,
    )

    # Wait until the match finishes, or until this connection is itself
    # superseded by a later reconnect, before letting this handler return.
    done_events = _get_done_events(app_state)
    done_event = done_events.get(match_id)
    if done_event:
        try:
            await _wait_done_or_superseded(done_event, new_conn)
        except Exception:
            pass


async def _safe_receive_text(ws: WebSocket) -> str | None:
    """Receive one text frame; return None on any error (disconnect, close, etc.)."""
    return await receive_text_frame(ws)


async def _wait_done_or_superseded(done_event: asyncio.Event, conn: SeatConnection) -> None:
    waiters = {
        asyncio.create_task(done_event.wait()),
        asyncio.create_task(conn.superseded.wait()),
    }
    _, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()


def _match_closed(match: Match, app_state: Any) -> bool:
    """Whether the match's driver has ended: finished, aborted, or crashed."""

    done = _get_done_events(app_state).get(match.match_id)
    if done is not None and done.is_set():
        return True
    return match.session.lifecycle.value in ("finished", "aborted")


# ---------------------------------------------------------------------------
# Spectator channel (Phase 36 Slice 3)
# ---------------------------------------------------------------------------


@router.websocket("/matches/{match_id}/spectate")
async def spectate_handler(ws: WebSocket, match_id: str) -> None:
    """Read-only view of a match (protocol §4).

    Holds a §13 connection slot for the session, exactly like the play channel:
    this endpoint is unauthenticated fan-out, which is why those caps had to land
    before it opened.
    """

    limiter: RateLimiter | None = getattr(ws.app.state, "rate_limiter", None)
    if limiter is None:
        await _spectate_session(ws, match_id)
        return

    ip = _client_ip(ws)
    try:
        limiter.acquire_connection(ip=ip, match_id=match_id, spectator=True)
    except RateLimitExceeded as exc:
        logger.warning(
            "rate_limited",
            match_id=match_id,
            seat=None,
            schema_version=1,
            scope=exc.scope,
            detail=exc.message,
        )
        await ws.accept()
        await _close(ws, _CLOSE_RATE_LIMITED, exc.scope)
        return

    try:
        await _spectate_session(ws, match_id)
    finally:
        limiter.release_connection(ip=ip, match_id=match_id, spectator=True)


async def _spectate_session(ws: WebSocket, match_id: str) -> None:
    """Drive one spectator session; see :func:`spectate_handler`."""

    registry: MatchRegistry = ws.app.state.match_registry
    try:
        match: Match = registry.get(match_id)
    except MatchNotFound:
        await ws.accept()
        await _close(ws, _CLOSE_MATCH_NOT_FOUND, "match_not_found")
        return

    await ws.accept()

    raw = await receive_text_frame(ws)
    if raw is None:  # gone, or a binary frame (already closed 1003)
        await _close(ws, _CLOSE_MALFORMED, "no_hello_received")
        return

    try:
        envelope = loads(raw)
    except SchemaVersionMismatch:
        await _close(ws, _CLOSE_SCHEMA_MISMATCH, "schema_version_mismatch")
        return
    except WireProtocolError:
        await _close(ws, _CLOSE_MALFORMED, "malformed_envelope")
        return

    if envelope.type != "spectator_hello":
        await _close(ws, _CLOSE_MALFORMED, f"expected_spectator_hello_got_{envelope.type}")
        return

    if WIRE_SCHEMA_VERSION not in envelope.payload.supported_schema_versions:
        await _close(ws, _CLOSE_SCHEMA_MISMATCH, "schema_version_mismatch")
        return

    app_state = ws.app.state
    conn = SpectatorConnection(websocket=ws)
    _start_writer(conn)

    # Order matters, and there must be no suspension between these two steps:
    # the welcome (which carries the attach-time history) has to be queued before
    # the connection joins the broadcast set, or a turn committing in between
    # would be delivered ahead of the history that should precede it. _send only
    # serialises and calls put_nowait, so it does not yield.
    try:
        await send_spectator_welcome(conn, match)
    except Exception:
        await _stop_writer(conn)
        await _close(ws, _CLOSE_SERVER_ERROR, "server_error")
        return

    if match.session.lifecycle.value in ("finished", "aborted"):
        # Nothing further will be broadcast; the welcome already carried the
        # whole public transcript.
        await _stop_writer(conn)
        await _close(ws, WS_CLOSE_NORMAL, "match_over")
        return

    conns = _get_match_conns(app_state).get(match_id)
    if conns is not None:
        conns.add_spectator(conn)
    else:
        # No connection registry yet because both seats have not arrived. Park;
        # the seat handler folds pending spectators in when it builds one.
        _get_pending_spectators(app_state).setdefault(match_id, []).append(conn)

    logger.info(
        "spectator_connected",
        match_id=match_id,
        seat=None,
        schema_version=1,
    )

    done_events = _get_done_events(app_state)
    if match_id not in done_events:
        done_events[match_id] = asyncio.Event()
    done_event = done_events[match_id]

    try:
        await _spectator_read_loop(ws, conn, match_id, done_event)
    finally:
        live = _get_match_conns(app_state).get(match_id)
        if live is not None:
            live.remove_spectator(conn)
        pending = _get_pending_spectators(app_state).get(match_id)
        if pending is not None and conn in pending:
            pending.remove(conn)
        await _stop_writer(conn)
        try:
            await ws.close(code=WS_CLOSE_NORMAL, reason="match_over")
        except Exception:
            pass
        logger.info(
            "spectator_disconnected",
            match_id=match_id,
            seat=None,
            schema_version=1,
        )


async def _spectator_read_loop(
    ws: WebSocket,
    conn: SpectatorConnection,
    match_id: str,
    done_event: asyncio.Event,
) -> None:
    """Consume a spectator's inbound frames until the match ends or it leaves.

    A spectator may send ping/pong; anything that tries to influence the match is
    answered with an error and the connection is closed. Reading also detects a
    departed spectator promptly, so it stops receiving broadcasts.
    """

    while not done_event.is_set():
        recv_task = asyncio.create_task(_safe_receive_text(ws))
        done_task = asyncio.create_task(done_event.wait())
        finished, pending = await asyncio.wait(
            {recv_task, done_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        if recv_task not in finished or recv_task.cancelled():
            return  # match over

        raw = recv_task.result()
        if raw is None:
            return  # spectator disconnected

        try:
            envelope = loads(raw)
        except WireProtocolError:
            continue  # a spectator cannot corrupt a match; ignore junk

        if envelope.type in ("ping", "pong"):
            continue

        # Anything else is an attempt to act, which a spectator may not do.
        await _send(
            conn,
            ErrorEnvelope(
                schema_version=WIRE_SCHEMA_VERSION,
                match_id=match_id,
                payload=ErrorBody(
                    code="protocol_violation",
                    message="Spectators may not send " + repr(envelope.type) + ".",
                ),
            ),
        )
        return


# ---------------------------------------------------------------------------
# Unknown endpoints (protocol section 9)
# ---------------------------------------------------------------------------


@router.websocket("/{path:path}")
async def unknown_endpoint_handler(ws: WebSocket, path: str) -> None:
    """Any other WebSocket path closes with ``4404 unsupported_endpoint``.

    Registered last, so it only catches what no route above matched. Starlette
    would otherwise refuse the handshake with HTTP 403, which a client cannot
    tell apart from a proxy rejecting it.
    """

    await ws.accept()
    await _close(ws, _CLOSE_UNSUPPORTED_ENDPOINT, "unsupported_endpoint")
