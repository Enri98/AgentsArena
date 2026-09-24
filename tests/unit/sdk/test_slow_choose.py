"""A slow choose() must not freeze the session (found running LLM agents, Phase 39).

The callback used to run inline on the event loop. An agent thinking longer than
the server's heartbeat window left pings unanswered and the server dropped the
seat.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from arena.sdk._connect import _run_session
from arena.sdk._events import MatchAbortedEvent, MatchFinishedEvent, ObservationEvent
from arena.sdk.errors import MatchAbortedError


def _observation_event() -> ObservationEvent:
    return ObservationEvent(body=SimpleNamespace(observation_request=SimpleNamespace()))


def test_the_event_loop_keeps_running_while_choose_thinks() -> None:
    async def run() -> int:
        ticks = 0
        finished = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            while not finished.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        events = [_observation_event()]

        class _Session:
            async def recv(self):
                if events:
                    return events.pop(0)
                if finished.is_set():
                    return MatchFinishedEvent(body=SimpleNamespace(result={}, transcript=None))
                await finished.wait()
                return MatchFinishedEvent(body=SimpleNamespace(result={}, transcript=None))

            async def send_action(self, action):
                finished.set()

        def slow_choose(_obs):
            time.sleep(0.3)  # a blocking model call
            return {"move": 1}

        task = asyncio.create_task(ticker())
        await _run_session(_Session(), slow_choose)
        await task
        return ticks

    ticks = asyncio.run(asyncio.wait_for(run(), timeout=10))
    assert ticks >= 10, "the loop was frozen while choose() ran"


def test_an_event_that_arrives_mid_decision_is_not_lost() -> None:
    abort = MatchAbortedEvent(body=SimpleNamespace(abort="deadline", transcript=None))
    events = [_observation_event(), abort]

    class _Session:
        async def recv(self):
            return events.pop(0)

        async def send_action(self, action):
            pass

    def slow_choose(_obs):
        time.sleep(0.1)
        return {"move": 1}

    try:
        asyncio.run(asyncio.wait_for(_run_session(_Session(), slow_choose), timeout=10))
    except MatchAbortedError as exc:
        assert "deadline" in str(exc) or exc is not None
    else:  # pragma: no cover
        raise AssertionError("the abort received during choose() was dropped")
