"""High-level connect() callback form."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from typing import Any, Callable

from arena.sdk._events import (
    ActionRejectedEvent,
    MatchAbortedEvent,
    MatchFinishedEvent,
    ObservationEvent,
)
from arena.sdk._session import Session
from arena.sdk.errors import MatchAbortedError, ProtocolError, SdkError


async def _next_event(session: Session, backlog: list[asyncio.Future[Any]]) -> Any:
    if backlog:
        return backlog.pop(0).result()  # re-raises what the receive raised
    return await session.recv()


def _run_in_daemon_thread(fn: Callable[[Any], Any], arg: Any) -> asyncio.Future[Any]:
    """Run ``fn(arg)`` on a daemon thread, resolving a future on this loop.

    Not ``asyncio.to_thread``: its executor threads are joined at shutdown, so
    cancelling ``connect()`` (a timeout, Ctrl+C) would still wait out a model
    call of up to minutes. A daemon thread is simply abandoned.
    """

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()

    def settle(result: Any, error: BaseException | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def work() -> None:
        try:
            result, error = fn(arg), None
        except BaseException as exc:  # noqa: BLE001 - handed to the awaiting task
            result, error = None, exc
        try:
            loop.call_soon_threadsafe(settle, result, error)
        except RuntimeError:
            pass  # the loop is gone: nobody is waiting any more

    threading.Thread(target=work, name="arena-sdk-choose", daemon=True).start()
    return future


async def _choose_while_serving(
    session: Session,
    choose: Callable[[Any], dict[str, Any]],
    observation: Any,
    backlog: list[asyncio.Future[Any]],
) -> dict[str, Any] | None:
    """Run the synchronous choose() off the loop while still receiving.

    An LLM agent can think for longer than the server's heartbeat allows. Called
    inline, choose() froze the event loop: pings went unanswered and the server
    dropped a healthy seat. Receiving concurrently lets the session answer pings
    (Session.recv replies to them itself); any other event is kept, in order, for
    the caller.

    Returns None when the match ended while choosing (an abort, or the connection
    failing): there is nothing left to send, and the caller reads the kept event
    next.
    """

    decision = _run_in_daemon_thread(choose, observation)
    receiving: asyncio.Future[Any] | None = None
    try:
        while not decision.done():
            receiving = asyncio.ensure_future(session.recv())
            await asyncio.wait({decision, receiving}, return_when=asyncio.FIRST_COMPLETED)
            if not receiving.done():
                break  # decided; the finally cancels the pending receive
            backlog.append(receiving)
            # Only an abort or a lost connection can end a match while this seat
            # is deciding; anything else (including a scripted LocalSession
            # running ahead) is handed back after the action is sent.
            error = receiving.exception()
            ended = isinstance(error, SdkError) or (
                error is None and isinstance(receiving.result(), MatchAbortedEvent)
            )
            receiving = None
            if ended:
                return None  # the decision is abandoned; its thread is a daemon
        return decision.result()
    finally:
        if receiving is not None and not receiving.done():
            receiving.cancel()
            try:
                await receiving
            except (asyncio.CancelledError, Exception):
                pass


async def _decide_and_send(
    session: Session,
    choose: Callable[[Any], dict[str, Any]],
    observation: Any,
    backlog: list[asyncio.Future[Any]],
) -> None:
    action = await _choose_while_serving(session, choose, observation, backlog)
    if action is None:
        return
    try:
        await session.send_action(action)
    except ProtocolError:
        # The server closed first (an abort racing our move). Its terminal frame,
        # if it arrived, is read next, so the caller learns why, not just that
        # the socket is gone.
        pass


async def _run_session(
    session: Session,
    choose: Callable[[Any], dict[str, Any]],
) -> tuple[dict[str, Any], Any]:
    """Drive a match session to completion using a choose() callback.

    Parameters
    ----------
    session:
        Any object implementing recv() / send_action() — Session or LocalSession.
    choose:
        Callable that accepts ObservationRequestPayload (from event.body.observation_request)
        and returns a raw action dict. It runs on a worker thread, so a slow agent
        does not stall the connection.

    Returns
    -------
    (result_dict, transcript)
        result_dict: the match result payload dict
        transcript: the RuntimeTranscriptPayload object

    Raises
    ------
    MatchAbortedError: if the match aborts before reaching a result.
    """
    obs: Any = None
    backlog: list[asyncio.Future[Any]] = []
    while True:
        event = await _next_event(session, backlog)

        if isinstance(event, ObservationEvent):
            obs = event.body.observation_request
            await _decide_and_send(session, choose, obs, backlog)

        elif isinstance(event, ActionRejectedEvent):
            # The turn is still open and no new observation comes: choose again,
            # unless the retry budget is spent (the abort follows).
            if obs is not None and event.body.retries_remaining > 0:
                await _decide_and_send(session, choose, obs, backlog)

        elif isinstance(event, MatchFinishedEvent):
            return event.body.result, event.body.transcript

        elif isinstance(event, MatchAbortedEvent):
            raise MatchAbortedError(event.body.abort, event.body.transcript)

        # match_state, turn_committed, error, welcome: drain silently


async def connect(
    url: str,
    seat: int,
    choose: Callable[[Any], dict[str, Any]],
    *,
    resume_token: str | None = None,
) -> tuple[dict[str, Any], Any]:
    """Connect to an arena.server and play a full match via the choose() callback.

    Parameters
    ----------
    url:
        WebSocket URL, e.g. ``ws://127.0.0.1:8080/matches/{match_id}/play?seat=0``.
    seat:
        Integer seat id (0 or 1).
    choose:
        Callable that accepts ObservationRequestPayload and returns a raw action dict.
    resume_token:
        Optional resume token from a prior Session; used for reconnection (Phase 32).

    Returns
    -------
    (result_dict, transcript)

    Raises
    ------
    MatchAbortedError: if the match aborts.
    ProtocolError subclass: on WS close with 4xxx code.
    HandshakeError: if hello/welcome handshake fails.
    """
    async with await Session.connect(url, seat, resume_token=resume_token) as session:
        return await _run_session(session, choose)


__all__: Sequence[str] = ["_run_session", "connect"]
