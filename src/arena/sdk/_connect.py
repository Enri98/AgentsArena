"""High-level connect() callback form."""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any, Callable

from arena.sdk._events import (
    ActionRejectedEvent,
    MatchAbortedEvent,
    MatchFinishedEvent,
    ObservationEvent,
)
from arena.sdk._session import Session
from arena.sdk.errors import MatchAbortedError


async def _next_event(session: object, backlog: list[asyncio.Future[Any]]) -> Any:
    if backlog:
        return backlog.pop(0).result()  # re-raises what the receive raised
    return await session.recv()  # type: ignore[union-attr]


async def _choose_while_serving(
    session: object,
    choose: Callable[[Any], dict[str, Any]],
    observation: Any,
    backlog: list[asyncio.Future[Any]],
) -> dict[str, Any]:
    """Run the synchronous choose() in a worker thread while still receiving.

    An LLM agent can think for longer than the server's heartbeat allows. Called
    inline, choose() froze the event loop: pings went unanswered and the server
    dropped a perfectly healthy seat. Receiving concurrently lets the session
    answer pings (Session.recv replies to them itself). An event that does
    arrive meanwhile, such as an abort, is kept and handed back in order.
    """

    decision = asyncio.ensure_future(asyncio.to_thread(choose, observation))
    receiving = asyncio.ensure_future(session.recv())  # type: ignore[union-attr]
    await asyncio.wait({decision, receiving}, return_when=asyncio.FIRST_COMPLETED)
    if receiving.done():
        backlog.append(receiving)
        return await decision
    receiving.cancel()
    try:
        await receiving
    except (asyncio.CancelledError, Exception):
        pass
    return decision.result()


async def _run_session(
    session: object,
    choose: Callable[[Any], dict[str, Any]],
) -> tuple[dict[str, Any], Any]:
    """Drive a match session to completion using a choose() callback.

    Parameters
    ----------
    session:
        Any object implementing recv() / send_action() — Session or LocalSession.
    choose:
        Callable that accepts ObservationRequestPayload (from event.body.observation_request)
        and returns a raw action dict.

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
            action = await _choose_while_serving(session, choose, obs, backlog)
            await session.send_action(action)  # type: ignore[union-attr]

        elif isinstance(event, ActionRejectedEvent):
            # The turn is still open and no new observation comes: choose again.
            # The server's retry budget decides when to stop.
            if obs is not None:
                action = await _choose_while_serving(session, choose, obs, backlog)
                await session.send_action(action)  # type: ignore[union-attr]

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
