"""Reconnect and throttling hardening (third adversarial review, Phase 38).

Each test reproduces a confirmed finding against a real uvicorn server:

* a reconnect while the old socket is still open (half-open TCP) must hand the
  active seat's turn to the new socket, not time out blaming it;
* a reconnect before the match starts is refused, not silently lost;
* superseded handlers release their connection slot, so repeated reconnects are
  not refused 4429;
* action throttling is not charged against the acting seat's deadline.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import websockets

from arena.adapters.in_process import ActionResponsePayload
from arena.adapters.websocket import dumps
from arena.adapters.websocket.envelope import ActionResponseEnvelope, HelloEnvelope
from arena.adapters.websocket.messages import ActionResponseBody, HelloBody
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration._ws_client import connect, play_scripted
from tests.integration.conftest import serve


def _hello(seat: int, token: str | None = None) -> HelloEnvelope:
    return HelloEnvelope(
        schema_version=3,
        seat=seat,
        payload=HelloBody(
            client_name="t",
            client_version="0",
            supported_schema_versions=[3],
            requested_seat=seat,
            resume_token=token,
        ),
    )


def _move(seat: int, action: dict[str, Any]) -> ActionResponseEnvelope:
    return ActionResponseEnvelope(
        schema_version=3,
        seat=seat,
        turn_id=str(uuid.uuid4()),
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id="tictactoe", schema_version=1, seat=seat, action=action
            )
        ),
    )


async def _until(ws: Any, wanted: str) -> dict:
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if frame["type"] == wanted:
            return frame


def _first_legal(frame: dict) -> dict:
    legal = frame["payload"]["observation_request"]["observation"]["legal_actions"]
    return {"row": legal[0]["row"], "column": legal[0]["column"]}


def _create(base: str, **extra: Any) -> dict:
    resp = httpx.post(f"{base}/matches", json={"game_id": "tictactoe", **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _play_out(ws: Any, seat: int) -> dict:
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if frame["type"] == "observation_request":
            await ws.send(dumps(_move(seat, _first_legal(frame))))
        if frame["type"] in ("match_finished", "match_aborted"):
            return frame


def test_a_half_open_takeover_hands_the_turn_to_the_new_socket() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(server) -> tuple[dict, dict]:
        match = _create(server.http_base_url, disconnect_grace_ms=10_000)
        old0 = await connect(match["seat_0_url"])
        ws1 = await connect(match["seat_1_url"])
        await old0.send(dumps(_hello(0)))
        token = (await _until(old0, "welcome"))["payload"]["resume_token"]
        await ws1.send(dumps(_hello(1)))
        await _until(ws1, "welcome")
        await _until(old0, "observation_request")

        # Seat 0 is to move. Its old socket stays open; a new one resumes.
        new0 = await connect(match["seat_0_url"])
        await new0.send(dumps(_hello(0, token)))
        await _until(new0, "welcome")
        results = await asyncio.gather(_play_out(new0, 0), _play_out(ws1, 1))
        try:
            await asyncio.wait_for(old0.recv(), timeout=5)
            old_closed = None
        except websockets.exceptions.ConnectionClosed as exc:
            old_closed = exc.rcvd.reason if exc.rcvd else "closed"
        await new0.close()
        await ws1.close()
        return results[0], {"old_closed": old_closed}

    with serve(app) as server:
        final, info = asyncio.run(asyncio.wait_for(run(server), timeout=60))
    assert final["type"] == "match_finished", final
    assert info["old_closed"] == "superseded"


def test_a_reconnect_before_the_match_starts_is_refused() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(server) -> tuple[int | None, str]:
        match = _create(server.http_base_url)
        ws0 = await connect(match["seat_0_url"])
        await ws0.send(dumps(_hello(0)))
        token = (await _until(ws0, "welcome"))["payload"]["resume_token"]
        again = await connect(match["seat_0_url"])
        await again.send(dumps(_hello(0, token)))
        try:
            await asyncio.wait_for(again.recv(), timeout=5)
            return None, "not closed"
        except websockets.exceptions.ConnectionClosed as exc:
            return (exc.rcvd.code, exc.rcvd.reason) if exc.rcvd else (None, "")
        finally:
            await ws0.close()

    with serve(app) as server:
        assert asyncio.run(asyncio.wait_for(run(server), timeout=30)) == (
            4409,
            "match_not_started",
        )


def test_repeated_reconnects_do_not_exhaust_the_per_match_connection_cap() -> None:
    # Default per-match cap (4); per-IP caps raised because tests share an IP.
    app = create_app(
        rate_limiter=RateLimiter(
            max_ws_connections_per_ip=99, max_match_creations_per_ip_per_min=99
        )
    )

    async def run(server) -> dict:
        match = _create(server.http_base_url, disconnect_grace_ms=10_000)
        ws0 = await connect(match["seat_0_url"])
        ws1 = await connect(match["seat_1_url"])
        await ws0.send(dumps(_hello(0)))
        token = (await _until(ws0, "welcome"))["payload"]["resume_token"]
        await ws1.send(dumps(_hello(1)))
        await _until(ws1, "welcome")
        await _until(ws0, "observation_request")

        for _ in range(5):
            fresh = await connect(match["seat_0_url"])
            await fresh.send(dumps(_hello(0, token)))
            token = (await _until(fresh, "welcome"))["payload"]["resume_token"]
            await ws0.close()
            ws0 = fresh
            await asyncio.sleep(0.1)  # let the superseded handler return

        results = await asyncio.gather(_play_out(ws0, 0), _play_out(ws1, 1))
        await ws0.close()
        await ws1.close()
        return results[0]

    with serve(app) as server:
        final = asyncio.run(asyncio.wait_for(run(server), timeout=60))
    assert final["type"] == "match_finished", final


def test_throttling_is_not_charged_against_the_deadline() -> None:
    """At 1 action/s and a 400 ms deadline, every throttled move waits longer
    than the deadline; the match must still finish."""

    app = create_app(
        rate_limiter=RateLimiter(
            max_actions_per_match_per_sec=1,
            max_ws_connections_per_ip=99,
            max_connections_per_match=99,
            max_match_creations_per_ip_per_min=99,
        )
    )

    async def run(server) -> Any:
        match = _create(server.http_base_url, per_turn_deadline_ms=400)
        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            (_, transcript), _ = await asyncio.gather(
                play_scripted(ws0, 0, lambda r: _legal(r)),
                play_scripted(ws1, 1, lambda r: _legal(r)),
            )
        return transcript

    def _legal(request: Any) -> dict:
        legal = request.observation["legal_actions"]
        return {"row": legal[0]["row"], "column": legal[0]["column"]}

    with serve(app) as server:
        transcript = asyncio.run(asyncio.wait_for(run(server), timeout=60))
    assert transcript.lifecycle == "finished"
