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
import json
import secrets as _secrets
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
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
from arena.core.exceptions import ArenaCoreError
from arena.core.public_view import Viewer, dump_config_for_seat, dump_config_for_viewer
from arena.match.local_match import apply_match_action, build_snapshot_for_viewer
from arena.match.transcript import (
    MATCH_TRANSCRIPT_SCHEMA_VERSION,
    VIEW_PUBLIC,
    transcript_view_for,
    turn_record_for_viewer,
)
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
from arena.server.config import MAX_TURNS_PER_MATCH

if TYPE_CHECKING:
    from fastapi import WebSocket

    from arena.server.registry import Match

logger = structlog.get_logger(__name__)

WS_CLOSE_NORMAL = 1000
#: Protocol section 9: internal server failure.
WS_CLOSE_SERVER_ERROR = 4500
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
    #: Set when a reconnect replaces this connection. Its handler then returns,
    #: releasing its protocol 13 connection slot instead of holding it until the
    #: match ends (the third reconnect in a match used to be refused 4429).
    superseded: asyncio.Event = field(default_factory=asyncio.Event)


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
    #: Watermark: the first turn index this spectator has not yet been sent.
    #: Its welcome carries every earlier turn in the transcript, so a
    #: turn_committed below the watermark would be a duplicate.
    next_turn_index: int = 0


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
        """Swap in a reconnected seat's new connection, with its own writer.

        Without a writer, every send to the reconnected seat would await its
        socket inside run_match, and a slow reader could stall the match driver
        again, the Phase 36 constraint. It would also open an await point in the
        middle of a broadcast, where a spectator could attach and receive turns
        twice.
        """

        old = self._seats.get(seat)
        if old is not None and old is not conn:
            if old.writer_task is not None:
                old.writer_task.cancel()
                old.writer_task = None
            old.superseded.set()
        self._seats[seat] = conn
        _start_writer(conn)

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
    # Every turn up to here is in the welcome's transcript; live frames resume
    # after it. See SpectatorConnection.next_turn_index.
    conn.next_turn_index = turn_count

    # Every spectator attaching at the same point gets the same bytes, so they
    # are built once. Serialising a long match's welcome is linear in its
    # length (about 200 ms at the turn cap), and a client looping attach and
    # detach made every match on the server pay that on the event loop.
    key = (turn_count, session.lifecycle.value)
    cached = _SPECTATOR_WELCOMES.get(match.match_id)
    if cached is not None and cached[0] == key:
        _SPECTATOR_WELCOMES.move_to_end(match.match_id)
        await _send_text(conn, cached[1])
        return

    transcript: RuntimeTranscriptPayload | None = None
    if local_match is not None:
        # Not swallowed: a spectator whose welcome lacks the history would never
        # get it (the watermark skips those turns). The handler closes it instead.
        transcript = _build_transcript_payload(session, None)

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
    text = dumps(env)
    _SPECTATOR_WELCOMES[match.match_id] = (key, text)
    _SPECTATOR_WELCOMES.move_to_end(match.match_id)
    while len(_SPECTATOR_WELCOMES) > _SPECTATOR_WELCOMES_MAX:
        _SPECTATOR_WELCOMES.popitem(last=False)
    await _send_text(conn, text)


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


@dataclass
class _ViewTranscript:
    """One viewer's match transcript of one match, grown one turn at a time."""

    base: dict[str, Any]
    turns: list[dict[str, Any]]


#: Incremental per-(match, viewer) transcripts. Turns are append-only, so each
#: turn is rendered for a viewer exactly once, however often a spectator
#: attaches or a seat reconnects. A per-attach rebuild is linear in match length,
#: about a second at the turn cap, and let one client stall every match on the
#: server by looping attach/detach. Bounded LRU; dropped on match eviction.
_VIEW_TRANSCRIPTS: "OrderedDict[tuple[str, Viewer], _ViewTranscript]" = OrderedDict()
_VIEW_TRANSCRIPTS_MAX = 12


#: The latest serialised spectator welcome per match, keyed by the point it was
#: built at: ``match_id -> ((turn_count, lifecycle), text)``. Bounded LRU.
_SPECTATOR_WELCOMES: "OrderedDict[str, tuple[tuple[int, str], str]]" = OrderedDict()
_SPECTATOR_WELCOMES_MAX = 16


def forget_match_transcripts(match_id: str) -> None:
    """Drop cached transcripts for an evicted match."""

    for key in [k for k in _VIEW_TRANSCRIPTS if k[0] == match_id]:
        del _VIEW_TRANSCRIPTS[key]
    _SPECTATOR_WELCOMES.pop(match_id, None)


def _match_transcript_for(session: MatchSession, viewer: Viewer) -> dict[str, Any]:
    local_match = session.local_match
    assert local_match is not None
    definition = session.definition
    hidden = definition.has_hidden_information
    # A perfect-information transcript is the full one for every viewer, and
    # the public rendering of a turn equals its authoritative one.
    render_as: Viewer = viewer if hidden else None
    key = (session.match_id, render_as)
    cached = _VIEW_TRANSCRIPTS.get(key)
    if cached is None:
        view, viewer_seat = transcript_view_for(definition, viewer)
        serializer = definition.serializer
        cached = _ViewTranscript(
            base={
                "game_id": definition.game_id,
                "schema_version": MATCH_TRANSCRIPT_SCHEMA_VERSION,
                "config": dump_config_for_viewer(serializer, local_match.config, render_as),
                "initial_snapshot": build_snapshot_for_viewer(
                    definition,
                    local_match.config,
                    local_match.rules_engine.initial_state(local_match.config),
                    render_as,
                ).model_dump(mode="json"),
                "view": view,
                "viewer_seat": viewer_seat,
            },
            turns=[],
        )
        _VIEW_TRANSCRIPTS[key] = cached
    for index in range(len(cached.turns), len(local_match.turns)):
        cached.turns.append(
            turn_record_for_viewer(local_match, index, render_as).model_dump(mode="json")
        )
    _VIEW_TRANSCRIPTS.move_to_end(key)
    while len(_VIEW_TRANSCRIPTS) > _VIEW_TRANSCRIPTS_MAX:
        _VIEW_TRANSCRIPTS.popitem(last=False)
    return {**cached.base, "turns": list(cached.turns)}


def _build_transcript_payload(session: MatchSession, viewer: Viewer) -> RuntimeTranscriptPayload:
    """The transcript ``viewer`` may receive: its seat's, or the public's (``None``).

    Never the full one: for a hidden-information game that exists only here.
    """

    if session.local_match is None:
        return RuntimeTranscriptPayload.model_validate(
            dump_runtime_transcript(session, viewer=viewer)
        )
    # Dump and validate only the small envelope (a placeholder stands in for the
    # match transcript), then attach the cached match transcript, which was
    # built from validated turn payloads. Dumping or re-validating a long one
    # would cost the very linear pass the cache exists to avoid.
    raw = dump_runtime_transcript(session, viewer=viewer, match_transcript={})
    envelope = RuntimeTranscriptPayload.model_validate(raw)
    return envelope.model_copy(
        update={"match_transcript": _match_transcript_for(session, viewer)}
    )


def _encode_transcript(payload: RuntimeTranscriptPayload) -> bytes:
    return json.dumps(payload.model_dump(mode="json")).encode("utf-8")


async def persist_public_transcript(app_state: Any, match: "Match") -> None:
    """Store the match's public transcript (Phase 40). Never raises.

    Called before ``match_finished`` / ``match_aborted`` go out, so a client
    that has seen the terminal frame can fetch the transcript at once. The
    stored body is exactly the transcript a spectator receives in that frame:
    the public view of a hidden-information game, the full transcript of a
    perfect-information one (which has nothing to hide). Encoding and disk I/O
    run in a worker thread.

    A failure is logged and swallowed: the match must still end properly for
    its seats. ``match.transcript_settled`` is set either way.
    """

    from arena.server.transcript_store import PUBLIC_AUDIENCE, TranscriptRejected

    store = getattr(app_state, "transcript_store", None)
    session = match.session
    try:
        if store is None or session.local_match is None:
            return
        payload = _build_transcript_payload(session, None)
        if session.definition.has_hidden_information and payload.view != VIEW_PUBLIC:
            raise RuntimeError(f"refusing to store a {payload.view!r} view")
        body = await asyncio.to_thread(_encode_transcript, payload)
        await asyncio.to_thread(store.put, match.match_id, body, audience=PUBLIC_AUDIENCE)
        logger.info(
            "transcript_stored",
            match_id=match.match_id,
            seat=None,
            schema_version=1,
            bytes=len(body),
        )
    except TranscriptRejected as exc:
        logger.warning(
            "transcript_not_stored",
            match_id=match.match_id,
            seat=None,
            schema_version=1,
            detail=str(exc),
        )
    except Exception:
        logger.exception(
            "transcript_store_failed",
            match_id=match.match_id,
            seat=None,
            schema_version=1,
        )
    finally:
        match.transcript_settled = True


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

    await _send_text(conn, dumps(envelope))


async def _send_text(conn: SeatConnection, text: str) -> None:
    """:func:`_send` for an envelope that is already serialised."""

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
        # Closed in the background: awaiting a close here would yield in the
        # middle of a broadcast, where a spectator attaching could be sent turns
        # its welcome already carried.
        asyncio.get_running_loop().create_task(_close_quietly(spectator.websocket))
        logger.warning(
            "spectator_dropped",
            schema_version=1,
            detail="outbox overflow; spectator could not keep up",
        )


async def _close_quietly(ws: "WebSocket") -> None:
    try:
        await ws.close(code=WS_CLOSE_NORMAL, reason="spectator_too_slow")
    except Exception:
        pass


def _enqueue_text(conn: Any, text: str) -> None:
    """Queue pre-serialised text on a connection whose writer is running."""

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


async def _broadcast_per_viewer(
    conns: "MatchConnections",
    build: Callable[[Viewer], Any],
    *,
    turn_index: int | None = None,
    shared: bool = False,
) -> None:
    """Send each recipient the envelope built for its own view (Phase 38).

    A seat's viewer is its seat; a spectator's is ``None``, the public. Each
    distinct view is built and serialised once: at most one per seat plus one
    public. With ``shared`` (a perfect-information game, where every view is the
    same) a single payload serves everyone.

    If building the public view fails, spectators are dropped rather than the
    match: an error in a view only a spectator needs must not end a match the
    seats are playing.

    ``turn_index`` marks a turn_committed frame. A spectator whose welcome already
    carried that turn is skipped.

    No await point until every recipient has been queued: a spectator attaching
    in the middle would otherwise be sent turns its welcome already carried.
    """

    rendered: dict[Viewer, str] = {}
    for conn in conns:
        viewer: Viewer = None if shared else conn.seat
        if turn_index is not None and turn_index < getattr(conn, "next_turn_index", 0):
            continue
        if viewer not in rendered:
            if conn.seat is None:
                try:
                    rendered[viewer] = dumps(build(viewer))
                except Exception as exc:
                    logger.warning(
                        "public_view_failed", schema_version=1, error=str(exc)
                    )
                    for spectator in conns.spectators():
                        spectator.outbox_overflowed = True
                    break
            else:
                rendered[viewer] = dumps(build(viewer))
        if conn.writer_task is None:
            await _send_now(conn, rendered[viewer])
        else:
            _enqueue_text(conn, rendered[viewer])
        if turn_index is not None and conn.seat is None:
            conn.next_turn_index = turn_index + 1
    await _shed_overflowed_spectators(conns)


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

    Phase 37: one step can commit several turns, such as an action followed by
    the chance nodes it leads to, or the chance nodes a match opens with. Sending
    only the last one would drop the action itself.

    Phase 38: each recipient gets its own view of every turn.
    """

    local_match = session.local_match
    if local_match is None:
        return
    for turn_index in range(since, len(local_match.turns)):
        await _broadcast_per_viewer(
            conns,
            lambda viewer, i=turn_index: _build_turn_committed_env(session, i, viewer),
            turn_index=turn_index,
            shared=not session.definition.has_hidden_information,
        )


def _build_turn_committed_env(session: MatchSession, turn_index: int, viewer: Viewer) -> Any:
    """One turn as ``viewer`` may see it.

    ``post_snapshot`` is the recipient's view and ``public_snapshot`` the public
    one (wire v3), so a seat's client also knows what spectators see. Events and
    the chance outcome are filtered to what the viewer may see.
    """

    local_match = session.local_match
    assert local_match is not None
    record = turn_record_for_viewer(local_match, turn_index, viewer)
    post_snapshot = record.post_snapshot.model_dump(mode="json")
    public_snapshot = build_snapshot_for_viewer(
        session.definition,
        local_match.config,
        local_match.turns[turn_index].post_state,
        None,
    ).model_dump(mode="json")
    # Phase 37: events are load-bearing. A chance outcome cannot be recomputed by
    # a client, so it has to be on the wire.
    event_payloads = [event.model_dump(mode="json") for event in record.events]
    turn_record_dict = {
        "turn_index": turn_index,
        "kind": record.kind,
        "seat": record.seat,
        "action": record.action,
        "outcome": record.outcome,
        "events": event_payloads,
        "post_snapshot": post_snapshot,
    }
    body = TurnCommittedBody(
        turn_record=turn_record_dict,
        post_snapshot=post_snapshot,
        public_snapshot=public_snapshot,
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
    def build(viewer: Viewer) -> Any:
        return MatchFinishedEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            match_id=session.match_id,
            payload=MatchFinishedBody(
                result={}, transcript=_build_transcript_payload(session, viewer)
            ),
        )

    await _broadcast_per_viewer(
        conns, build, shared=not session.definition.has_hidden_information
    )


async def _broadcast_match_aborted(
    conns: "MatchConnections",
    session: MatchSession,
) -> None:
    abort_payload = RuntimeAbortPayload(
        reason=session.abort.reason.value,
        message=session.abort.message,
        cause_type=session.abort.cause_type,
        cause_message=session.abort.cause_message,
    )

    def build(viewer: Viewer) -> Any:
        return MatchAbortedEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            match_id=session.match_id,
            payload=MatchAbortedBody(
                abort=abort_payload, transcript=_build_transcript_payload(session, viewer)
            ),
        )

    await _broadcast_per_viewer(
        conns, build, shared=not session.definition.has_hidden_information
    )


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


#: Protocol sections 3 and 9: a binary frame closes the connection with 1003.
WS_CLOSE_UNSUPPORTED_DATA = 1003


async def receive_text_frame(ws: "WebSocket") -> str | None:
    """Receive one text frame; ``None`` once the connection is gone.

    A binary frame closes the connection with ``1003 unsupported_data`` (section
    3) and also returns ``None``: to the caller it is a disconnect, and the seat
    can resume. ``receive_text`` raised on a binary frame, which every caller
    treated as a silent disconnect.
    """

    try:
        message = await ws.receive()
    except Exception:
        return None
    if message.get("type") != "websocket.receive":
        return None
    text = message.get("text")
    if text is None:
        try:
            await ws.close(code=WS_CLOSE_UNSUPPORTED_DATA, reason="unsupported_data")
        except Exception:
            pass
        return None
    return text


async def _safe_receive_text(ws: "WebSocket") -> str | None:
    """Receive one text frame; return None on any error (disconnect, close, etc.)."""
    return await receive_text_frame(ws)


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
    return await receive_text_frame(ws)


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
        # Checked before every read, not only while one is pending: the deadline
        # can fire during the throttle sleep below, and the read after it used
        # to wait with no deadline at all.
        if deadline_event is not None and deadline_event.is_set():
            return None, None, _DEADLINE_EXPIRED

        # Start one receive_text() as a task so we can race it against the deadline.
        recv_task = asyncio.create_task(_receive_one_text(active_conn.websocket))

        if deadline_event is not None:
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
            # Protocol 13: throttle, don't disconnect. Waiting bounds the work
            # the loop does per match exactly as closing did, but a fast,
            # legitimate agent is no longer shed. The frame already arrived, so
            # the wait is the server's, not the seat's: it is not charged
            # against the per-turn deadline (the window is shared by both seats,
            # so charging it would expire a seat for its opponent's speed).
            delay = limiter.reserve_action(match_id=match_id)
            if delay > 0:
                logger.info(
                    "action_throttled",
                    match_id=match_id,
                    seat=active_conn.seat,
                    schema_version=1,
                    delay_ms=int(delay * 1000),
                )
                await asyncio.sleep(delay)

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

    async def _abort(
        reason: AbortReason,
        message: str,
        *,
        seat: int | None,
        log_reason: str,
        close_reason: str,
        close_code: int = WS_CLOSE_NORMAL,
    ) -> None:
        """Abort the match: record it, tell everyone, close both seats."""

        nonlocal session
        session = arena.abort_session(session, reason=reason, message=message)
        match.session = session
        await persist_public_transcript(app_state, match)
        await _broadcast_match_state(conns, session)
        await _broadcast_match_aborted(conns, session)
        logger.info(
            "match_aborted",
            match_id=session.match_id,
            seat=seat,
            schema_version=1,
            reason=log_reason,
        )
        await _close_both(conns, close_code, close_reason)

    # One writer task per seat for the life of the match: the driver enqueues and
    # never blocks on a socket.
    for _seat_conn in conns.seats():
        _start_writer(_seat_conn)

    try:
        if session.lifecycle is RuntimeLifecycle.ABORTED:
            await persist_public_transcript(app_state, match)
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
            # One absolute deadline per turn (section 11): it keeps running while
            # the seat is disconnected, and a reconnect does not restart it. A
            # fresh budget per reconnect let a seat hold its turn for ever by
            # reconnecting just before each deadline.
            deadline_event: asyncio.Event | None = None
            deadline_timer_task: asyncio.Task | None = None
            deadline_at: float | None = None
            if deadline_s:
                deadline_at = asyncio.get_running_loop().time() + deadline_s
                deadline_event = asyncio.Event()
                deadline_timer_task = asyncio.create_task(
                    _deadline_sleep(deadline_event, deadline_s)
                )

            async def _deadline_abort() -> None:
                _cancel_task(deadline_timer_task)
                logger.warning(
                    "turn_deadline_expired",
                    match_id=session.match_id,
                    seat=active_seat,
                    schema_version=1,
                )
                await _abort(
                    AbortReason.TURN_DEADLINE_EXPIRED,
                    "Per-turn deadline expired.",
                    seat=active_seat,
                    log_reason="turn_deadline_expired",
                    close_reason="turn_deadline_expired",
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
                    await _deadline_abort()
                    return

                # --- Disconnect handling ---
                if error_msg == "disconnected":
                    # A heartbeat timeout is a disconnect like any other: the
                    # grace period starts when the socket closes (section 8.10),
                    # so a seat whose network stalled can still resume.
                    timed_out = active_conn.heartbeat_timed_out
                    grace_s = match.disconnect_grace_ms / 1000.0
                    reconnect_events = _get_reconnect_events(app_state)
                    reconnect_event = (
                        reconnect_events.get(match.match_id, {}).get(active_seat)
                    )
                    logger.info(
                        "heartbeat_timeout" if timed_out else "seat_disconnected",
                        match_id=match.match_id,
                        seat=active_seat,
                        schema_version=1,
                        grace_ms=match.disconnect_grace_ms,
                    )
                    lost_reason = (
                        AbortReason.HEARTBEAT_TIMEOUT
                        if timed_out
                        else AbortReason.PEER_DISCONNECTED
                    )

                    if reconnect_event is None:
                        # No event registered (should not happen); abort now.
                        _cancel_task(deadline_timer_task)
                        await _abort(
                            lost_reason,
                            "Seat disconnected and did not reconnect within grace period.",
                            seat=active_seat,
                            log_reason="peer_disconnected",
                            close_reason="peer_disconnected",
                        )
                        return

                    # The reconnect handler swaps the new connection into
                    # conns itself. If that already happened, there is nothing
                    # to wait for; checking first also closes the window where
                    # clearing the event would discard a reconnect that beat us.
                    if conns[active_seat] is active_conn:
                        reconnect_event.clear()
                        # The deadline keeps running (section 11): wait for a
                        # reconnect, the deadline, or the end of the grace.
                        waiters = {asyncio.ensure_future(reconnect_event.wait())}
                        if deadline_event is not None:
                            waiters.add(asyncio.ensure_future(deadline_event.wait()))
                        await asyncio.wait(
                            waiters, timeout=grace_s, return_when=asyncio.FIRST_COMPLETED
                        )
                        for waiter in waiters:
                            waiter.cancel()
                        await asyncio.gather(*waiters, return_exceptions=True)

                    reconnected = (
                        conns[active_seat] is not active_conn or reconnect_event.is_set()
                    )
                    if deadline_event is not None and deadline_event.is_set():
                        await _deadline_abort()
                        return
                    if not reconnected:
                        _cancel_task(deadline_timer_task)
                        await _abort(
                            lost_reason,
                            "Seat disconnected and did not reconnect within grace period.",
                            seat=active_seat,
                            log_reason=f"{lost_reason.value}_grace_expired",
                            close_reason="peer_disconnected",
                        )
                        return

                    # Reconnected: use the connection the handler swapped in.
                    new_conn = conns[active_seat]
                    if new_conn is active_conn:
                        new_conn = (
                            _get_reconnect_conns(app_state)
                            .get(match.match_id, {})
                            .get(active_seat)
                        )
                    if new_conn is None:
                        _cancel_task(deadline_timer_task)
                        await _abort(
                            AbortReason.PEER_DISCONNECTED,
                            "Reconnect event set but no new connection found.",
                            seat=active_seat,
                            log_reason="peer_disconnected_no_conn",
                            close_reason="peer_disconnected",
                        )
                        return

                    conns.replace_seat(active_seat, new_conn)
                    active_conn = new_conn

                    # Replace heartbeat task for the reconnected seat.
                    await _cancel_hb()
                    hb_task = _start_hb(new_conn)

                    # Re-send the observation request with what is left of the
                    # original deadline, not a fresh budget.
                    resend = obs_env
                    if deadline_at is not None:
                        remaining_ms = int(
                            (deadline_at - asyncio.get_running_loop().time()) * 1000
                        )
                        resend = obs_env.model_copy(
                            update={
                                "payload": obs_body.model_copy(
                                    update={"deadline_ms": max(1, remaining_ms)}
                                )
                            }
                        )
                    await _send(active_conn, resend)
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
                        retries_remaining=retries_left,
                    )

                    if retries_left == 0:
                        # §8.6: rejected(0) → match_state(aborted) → match_aborted → close
                        rej_env = _make_rejected_env(
                            session, active_seat, turn_id, domain_err, 0
                        )
                        await _send(active_conn, rej_env)
                        _cancel_task(deadline_timer_task)
                        await _abort(
                            AbortReason.ADAPTER_ERROR,
                            "Retry budget exhausted.",
                            seat=active_seat,
                            log_reason="adapter_error_budget_exhausted",
                            close_reason="adapter_error",
                        )
                        return

                    # Protocol 8.6: retries_remaining counts the further attempts
                    # still allowed, so it is reported before this rejection spends
                    # one; 0 appears only on the final rejection, right before the
                    # abort. (Reporting it after decrementing made a compliant
                    # client stop one attempt early.)
                    rej_env = _make_rejected_env(
                        session, active_seat, turn_id, domain_err, retries_left
                    )
                    retries_left -= 1
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
                        retries_remaining=retries_left,
                    )

                    if retries_left == 0:
                        rej_env = _make_rejected_env(
                            session, active_seat, turn_id, domain_err, 0
                        )
                        await _send(active_conn, rej_env)
                        _cancel_task(deadline_timer_task)
                        await _abort(
                            AbortReason.ADAPTER_ERROR,
                            "Retry budget exhausted.",
                            seat=active_seat,
                            log_reason="adapter_error_budget_exhausted",
                            close_reason="adapter_error",
                        )
                        return

                    # Protocol 8.6: retries_remaining counts the further attempts
                    # still allowed, so it is reported before this rejection spends
                    # one; 0 appears only on the final rejection, right before the
                    # abort. (Reporting it after decrementing made a compliant
                    # client stop one attempt early.)
                    rej_env = _make_rejected_env(
                        session, active_seat, turn_id, domain_err, retries_left
                    )
                    retries_left -= 1
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

                # A game can loop without end (two Pig seats that only ever
                # roll). Holding both seat URLs is enough to pin server memory
                # that way, so the server bounds every match.
                turn_cap = getattr(app_state, "max_turns_per_match", MAX_TURNS_PER_MATCH)
                if (
                    session.lifecycle is RuntimeLifecycle.RUNNING
                    and len(next_match.turns) >= turn_cap
                ):
                    logger.warning(
                        "turn_limit_exceeded",
                        match_id=session.match_id,
                        seat=None,
                        schema_version=1,
                        turn_cap=turn_cap,
                    )
                    await _abort(
                        AbortReason.TURN_LIMIT_EXCEEDED,
                        f"The match exceeded the server's cap of {turn_cap} turns.",
                        seat=None,
                        log_reason="turn_limit_exceeded",
                        close_reason="turn_limit_exceeded",
                    )
                    return

        # Match reached terminal state.
        await persist_public_transcript(app_state, match)
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

    except Exception:
        # A bug must not leave a match "running" until eviction with both seats
        # hanging on a dead driver: abort it, tell everyone, close with 4500.
        logger.exception(
            "run_match_error", match_id=match.match_id, seat=None, schema_version=1
        )
        if match.session.lifecycle not in (
            RuntimeLifecycle.FINISHED,
            RuntimeLifecycle.ABORTED,
        ):
            session = match.session
            try:
                await _abort(
                    AbortReason.RUNTIME_ERROR,
                    "The server failed while running the match.",
                    seat=None,
                    log_reason="server_error",
                    close_reason="server_error",
                    close_code=WS_CLOSE_SERVER_ERROR,
                )
            except Exception:
                logger.exception(
                    "run_match_abort_failed",
                    match_id=match.match_id,
                    seat=None,
                    schema_version=1,
                )
                await _close_both(conns, WS_CLOSE_SERVER_ERROR, "server_error")

    finally:
        # However the driver ended, a transcript GET must stop answering 409.
        match.transcript_settled = True
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


async def send_welcome(
    conn: SeatConnection, match: "Match", *, with_transcript: bool = False
) -> None:
    """Send a welcome envelope to one seat after a successful hello handshake.

    Generates and stores a fresh resume_token in match.resume_tokens[seat].
    The token rotates on every call (initial connect and every reconnect).

    Phase 38: ``match_config`` is the seat's own view of the config, and on a
    reconnect (``with_transcript``) the welcome carries the seat's transcript so
    far, which protocol §11 promised but v1 never sent. It is the seat's own
    view, so reconnecting adds no information the seat did not already have.
    """
    players = _build_player_info(match)
    match_config_dict = dump_config_for_seat(
        match.definition.serializer, match.match_config, conn.seat
    )
    transcript: RuntimeTranscriptPayload | None = None
    if with_transcript and match.session.local_match is not None:
        transcript = _build_transcript_payload(match.session, conn.seat)

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
        transcript=transcript,
    )
    env = WelcomeEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=match.match_id,
        seat=conn.seat,
        payload=body,
    )
    await _send(conn, env)
