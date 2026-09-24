"""Server hardening from the pre-Phase 40 adversarial review, over real TCP.

Each test is a confirmed finding, reproduced with raw WebSocket clients:

* after seat 0 resumed once, a fresh ``hello`` could claim seat 0 mid-match and
  read its private transcript (the claimant was welcomed, resumed with its new
  token, and the real player was locked out);
* a seat could hold its turn for ever, by reconnecting (each reconnect granted a
  fresh deadline) or by bursting duplicate frames into the action throttle (the
  deadline fired during the throttle sleep and was then never checked again).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx
from websockets.asyncio.client import connect as ws_connect

from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration.conftest import serve


def _create(base: str, game: str, **extra: Any) -> dict[str, Any]:
    body = {"game_id": game, "players": [{"label": "a"}, {"label": "b"}], **extra}
    resp = httpx.post(f"{base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _hello(seat: int, token: str | None = None) -> str:
    return json.dumps(
        {
            "type": "hello",
            "schema_version": 3,
            "seat": seat,
            "payload": {
                "client_name": "test",
                "client_version": "0",
                "supported_schema_versions": [3],
                "auth": None,
                "requested_seat": seat,
                "resume_token": token,
            },
        }
    )


def _action(match_id: str, seat: int, game: str, action: dict, turn_id: str) -> str:
    return json.dumps(
        {
            "type": "action_response",
            "schema_version": 3,
            "match_id": match_id,
            "seat": seat,
            "turn_id": turn_id,
            "payload": {
                "action_response": {
                    "game_id": game,
                    "schema_version": 1,
                    "seat": seat,
                    "action": action,
                }
            },
        }
    )


def _pong(match_id: str, nonce: str) -> str:
    return json.dumps(
        {"type": "pong", "schema_version": 3, "match_id": match_id, "payload": {"nonce": nonce}}
    )


async def _join(ws_base: str, match_id: str, seat: int, token: str | None = None) -> Any:
    ws = await ws_connect(
        f"{ws_base}/matches/{match_id}/play?seat={seat}", ping_interval=None, max_size=None
    )
    await ws.send(_hello(seat, token))
    return ws


async def _recv(ws: Any, timeout: float = 5.0) -> dict[str, Any]:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def _until(ws: Any, frame_type: str, match_id: str) -> dict[str, Any]:
    while True:
        frame = await _recv(ws)
        if frame["type"] == "ping":
            await ws.send(_pong(match_id, frame["payload"]["nonce"]))
        if frame["type"] == frame_type:
            return frame


async def _closed_with(ws: Any) -> tuple[int | None, str | None]:
    try:
        while True:
            await asyncio.wait_for(ws.recv(), 5)
    except Exception:
        pass
    return ws.close_code, ws.close_reason


def test_a_fresh_hello_cannot_claim_a_seat_mid_match() -> None:
    async def run(base: str, ws_base: str) -> dict[str, Any]:
        match = _create(
            base, "liarsdice", per_turn_deadline_ms=20_000, disconnect_grace_ms=5_000
        )
        mid = match["match_id"]
        seat0 = await _join(ws_base, mid, 0)
        token = (await _recv(seat0))["payload"]["resume_token"]
        seat1 = await _join(ws_base, mid, 1)
        await _recv(seat1)
        await asyncio.sleep(0.3)

        # Seat 0 resumes once, as the SDK does after any network blip.
        resumed = await _join(ws_base, mid, 0, token)
        token = (await _recv(resumed))["payload"]["resume_token"]
        await asyncio.sleep(0.3)

        claimant = await _join(ws_base, mid, 0)
        claim = await _closed_with(claimant)

        # The real player's token still works.
        again = await _join(ws_base, mid, 0, token)
        welcome = await _recv(again)
        for ws in (seat0, seat1, resumed, again):
            await ws.close()
        return {"claim": claim, "welcome": welcome["type"]}

    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as server:
        out = asyncio.run(
            asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 40)
        )
    assert out["claim"] == (4409, "seat_taken")
    assert out["welcome"] == "welcome"


def test_reconnecting_does_not_restart_the_deadline() -> None:
    async def run(base: str, ws_base: str) -> dict[str, Any]:
        match = _create(base, "pig", per_turn_deadline_ms=1_500, disconnect_grace_ms=5_000)
        mid = match["match_id"]
        seat0 = await _join(ws_base, mid, 0)
        token = (await _recv(seat0))["payload"]["resume_token"]
        seat1 = await _join(ws_base, mid, 1)
        await _recv(seat1)
        await _until(seat0, "observation_request", mid)

        started = time.monotonic()
        deadlines: list[int] = []
        reason = None
        conns = [seat0, seat1]
        while time.monotonic() - started < 8 and reason is None:
            await asyncio.sleep(0.4)
            ws = await _join(ws_base, mid, 0, token)
            conns.append(ws)
            try:
                while True:
                    frame = await _recv(ws, timeout=3)
                    if frame["type"] == "welcome":
                        token = frame["payload"]["resume_token"]
                    elif frame["type"] == "observation_request":
                        deadlines.append(frame["payload"]["deadline_ms"])
                        break
                    elif frame["type"] == "match_aborted":
                        reason = frame["payload"]["abort"]["reason"]
                        break
            except Exception:
                reason = reason or "closed"
        elapsed = time.monotonic() - started
        for ws in conns:
            await ws.close()
        return {"reason": reason, "elapsed": elapsed, "deadlines": deadlines}

    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as server:
        out = asyncio.run(
            asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 40)
        )
    assert out["reason"] in ("turn_deadline_expired", "closed"), out
    assert out["elapsed"] < 4, out
    # Every re-sent observation carries what is left, never a fresh 1500 ms.
    assert all(d < 1_500 for d in out["deadlines"]), out
    assert out["deadlines"] == sorted(out["deadlines"], reverse=True), out


def test_the_deadline_survives_the_action_throttle() -> None:
    async def run(base: str, ws_base: str) -> dict[str, Any]:
        match = _create(base, "pig", per_turn_deadline_ms=1_000, disconnect_grace_ms=1_000)
        mid = match["match_id"]
        seat0 = await _join(ws_base, mid, 0)
        await _recv(seat0)
        seat1 = await _join(ws_base, mid, 1)
        await _recv(seat1)
        await _until(seat0, "observation_request", mid)

        turn_id = str(uuid.uuid4())
        # Holding on a zero turn total is illegal: rejected once, then every
        # duplicate is dropped, but each still reserves a throttle slot.
        for _ in range(26):
            await seat0.send(_action(mid, 0, "pig", {"choice": "hold"}, turn_id))
        started = time.monotonic()
        reason = None
        while time.monotonic() - started < 10 and reason is None:
            try:
                frame = await _recv(seat0, timeout=1)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
            if frame["type"] == "ping":
                await seat0.send(_pong(mid, frame["payload"]["nonce"]))
            elif frame["type"] == "match_aborted":
                reason = frame["payload"]["abort"]["reason"]
        elapsed = time.monotonic() - started
        await seat0.close()
        await seat1.close()
        return {"reason": reason, "elapsed": elapsed}

    app = create_app(rate_limiter=RateLimiter(), heartbeat_interval_ms=2_000)
    with serve(app) as server:
        out = asyncio.run(
            asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 40)
        )
    assert out["reason"] == "turn_deadline_expired", out
    assert out["elapsed"] < 5, out
