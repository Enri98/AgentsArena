"""FastAPI WebSocket routes for arena.server.

WS /matches/{match_id}/play?seat={0|1}  -- primary play channel (§4)
WS /matches/{match_id}/spectate          -- reserved; closes 4404 (§4)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket

from arena.adapters.websocket import WIRE_SCHEMA_VERSION, loads
from arena.adapters.websocket.errors import SchemaVersionMismatch, WireProtocolError
from arena.server.errors import MatchNotFound
from arena.server.registry import Match, MatchRegistry
from arena.server.runtime_bridge import SeatConnection, run_match, send_welcome

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Close codes (protocol §9) ──────────────────────────────────────────────
_CLOSE_SCHEMA_MISMATCH = 4400
_CLOSE_UNSUPPORTED_ENDPOINT = 4404
_CLOSE_SEAT_TAKEN = 4409
_CLOSE_MATCH_NOT_FOUND = 4410
_CLOSE_MALFORMED = 4422
_CLOSE_SERVER_ERROR = 4500


# ── Per-match seat-slot tracking ──────────────────────────────────────────
# match_id → {seat: SeatConnection | None}
# Accessed only from async handlers (single-threaded event loop); no lock needed.

def _get_seat_slots(app_state: Any) -> dict[str, dict[int, SeatConnection | None]]:
    if not hasattr(app_state, "_ws_seat_slots"):
        app_state._ws_seat_slots = {}
    return app_state._ws_seat_slots


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


@router.websocket("/matches/{match_id}/spectate")
async def spectate_reserved(ws: WebSocket, match_id: str) -> None:
    """Reserved endpoint (§4). Accepts then immediately closes with 4404."""
    await ws.accept()
    await _close(ws, _CLOSE_UNSUPPORTED_ENDPOINT, "unsupported_endpoint")


@router.websocket("/matches/{match_id}/play")
async def play_handler(ws: WebSocket, match_id: str, seat: int = -1) -> None:
    """Primary play channel (protocol §5/§8/§10)."""

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
    try:
        raw = await ws.receive_text()
    except Exception:
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

    if envelope.type != "hello":
        await _close(ws, _CLOSE_MALFORMED, f"expected_hello_got_{envelope.type}")
        return

    hello = envelope.payload

    # 5. Validate requested_seat matches the URL ?seat= param.
    if hello.requested_seat != seat:
        await _close(ws, _CLOSE_MALFORMED, "seat_mismatch")
        return

    # 6. Schema-version negotiation: require 1 in client's supported list.
    if WIRE_SCHEMA_VERSION not in hello.supported_schema_versions:
        await _close(ws, _CLOSE_SCHEMA_MISMATCH, "schema_version_mismatch")
        return

    # 7. Check seat occupancy.
    app_state = ws.app.state
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
        logger.warning("Failed to send welcome for match %s seat %d: %s", match_id, seat, exc)
        seat_slots[match_id][seat] = None
        await _close(ws, _CLOSE_SERVER_ERROR, "server_error")
        return

    logger.debug("Seat %d joined match %s", seat, match_id)

    # 9. Wait until both seats are connected; idle seat drains receives to detect disconnect.
    ready_events = _get_ready_events(app_state)
    if match_id not in ready_events:
        ready_events[match_id] = asyncio.Event()
    ready_event = ready_events[match_id]

    done_events = _get_done_events(app_state)
    if match_id not in done_events:
        done_events[match_id] = asyncio.Event()
    done_event = done_events[match_id]

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
                if result is None:
                    # WebSocket closed before second seat arrived.
                    seat_slots[match_id][seat] = None
                    return
                # Received some unexpected frame while idle; discard (match not started).

    # 10. Both seats are connected.  Seat 1's handler drives run_match; seat 0 just waits
    #     for the done_event (set by run_match when the match ends and both WS are closed).
    if seat == 1:
        conn0 = seat_slots[match_id][0]
        conn1 = seat_slots[match_id][1]
        assert conn0 is not None
        assert conn1 is not None
        try:
            await run_match(match, (conn0, conn1))
        except Exception as exc:
            logger.exception("run_match error for match %s: %s", match_id, exc)
        finally:
            done_event.set()
            seat_slots[match_id] = {0: None, 1: None}
    else:
        # Seat 0: wait until run_match signals it's done.
        # Do NOT call receive_text here — run_match receives from ws0 when it's seat 0's turn.
        try:
            await done_event.wait()
        except Exception:
            pass
        finally:
            seat_slots[match_id][seat] = None


async def _safe_receive_text(ws: WebSocket) -> str | None:
    """Receive one text frame; return None on any error (disconnect, close, etc.)."""
    try:
        return await ws.receive_text()
    except Exception:
        return None
