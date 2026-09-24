"""The SDK with slow and wrong agents, against a real server (Phase 39 reviews).

LLM agents think for seconds to minutes and make illegal moves. Each test is a
confirmed finding: a slow agent must survive the heartbeat; an abort that
arrives while it thinks must surface as MatchAbortedError; a spent retry budget
must not trigger another (possibly minutes-long) decision; and cancelling
connect() must not wait out a decision in progress.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import pytest

from arena.sdk import connect
from arena.sdk.errors import MatchAbortedError
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration.conftest import serve


def _create(server: Any, **extra: Any) -> dict:
    resp = httpx.post(
        f"{server.http_base_url}/matches", json={"game_id": "tictactoe", **extra}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _first_legal(request: Any) -> dict:
    legal = request.observation["legal_actions"]
    return {"row": legal[0]["row"], "column": legal[0]["column"]}


def test_a_slow_agent_survives_the_heartbeat() -> None:
    app = create_app(
        rate_limiter=RateLimiter.unlimited(), heartbeat_interval_ms=200, heartbeat_max_misses=2
    )

    def slow(request: Any) -> dict:
        time.sleep(1.2)  # six heartbeat intervals
        return _first_legal(request)

    async def run(server: Any) -> Any:
        match = _create(server, per_turn_deadline_ms=10_000)
        results = await asyncio.gather(
            connect(match["seat_0_url"], 0, slow),
            connect(match["seat_1_url"], 1, _first_legal),
        )
        return results[0][1]

    with serve(app) as server:
        transcript = asyncio.run(asyncio.wait_for(run(server), timeout=60))
    assert transcript.lifecycle == "finished"


def test_an_abort_while_deciding_is_a_match_aborted_error() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    def too_slow(request: Any) -> dict:
        time.sleep(1.5)
        return _first_legal(request)

    async def run(server: Any) -> list[Any]:
        match = _create(server, per_turn_deadline_ms=500)
        return await asyncio.gather(
            connect(match["seat_0_url"], 0, too_slow),
            connect(match["seat_1_url"], 1, _first_legal),
            return_exceptions=True,
        )

    with serve(app) as server:
        results = asyncio.run(asyncio.wait_for(run(server), timeout=60))
    assert all(isinstance(r, MatchAbortedError) for r in results), results
    assert "turn_deadline_expired" in str(results[0])


def test_a_spent_retry_budget_stops_choosing() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    calls = 0

    def illegal(_request: Any) -> dict:
        nonlocal calls
        calls += 1
        return {"row": 9, "column": 9}

    async def run(server: Any) -> list[Any]:
        match = _create(server, per_action_retry_budget=1)
        return await asyncio.gather(
            connect(match["seat_0_url"], 0, illegal),
            connect(match["seat_1_url"], 1, _first_legal),
            return_exceptions=True,
        )

    with serve(app) as server:
        results = asyncio.run(asyncio.wait_for(run(server), timeout=60))
    assert isinstance(results[0], MatchAbortedError), results[0]
    assert "adapter_error" in str(results[0])
    assert calls == 2  # the first try plus one retry; nothing after the budget


def test_cancelling_connect_does_not_wait_for_the_decision() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    def very_slow(request: Any) -> dict:
        time.sleep(5)
        return _first_legal(request)

    async def run(server: Any) -> float:
        match = _create(server, per_turn_deadline_ms=20_000)
        other = asyncio.create_task(connect(match["seat_1_url"], 1, _first_legal))
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(connect(match["seat_0_url"], 0, very_slow), timeout=0.8)
        elapsed = time.monotonic() - started
        other.cancel()
        try:
            await other
        except (asyncio.CancelledError, Exception):
            pass
        return elapsed

    with serve(app) as server:
        elapsed = asyncio.run(asyncio.wait_for(run(server), timeout=60))
    assert elapsed < 3.0, elapsed
