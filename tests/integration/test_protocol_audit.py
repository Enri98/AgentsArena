"""Fixes from the Phase 42 audit of docs/NETWORK_PROTOCOL.md against the code.

- ``result`` was always ``{}`` in match_finished and null in match_state and
  ``GET /matches/{id}``; it now carries the result, as the spec said.
- A seat could send unlimited malformed frames, each answered and logged; past
  a cap per turn it is now closed 4422.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from websockets.exceptions import ConnectionClosed

from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from arena.server.runtime_bridge import MAX_PROTOCOL_ERRORS_PER_TURN
from tests.integration._ws_client import connect, play_scripted
from tests.integration.conftest import serve


def _first_legal(payload: Any) -> dict[str, Any]:
    return payload.observation["legal_actions"][0]


def test_a_finished_match_reports_its_result_everywhere() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as server:
        match = httpx.post(
            f"{server.http_base_url}/matches", json={"game_id": "tictactoe"}
        ).json()
        frames: list[str] = []

        async def run() -> tuple[Any, Any]:
            ws0 = await connect(match["seat_0_url"])
            ws1 = await connect(match["seat_1_url"])
            try:
                return await asyncio.gather(
                    play_scripted(ws0, 0, _first_legal, frames=frames),
                    play_scripted(ws1, 1, _first_legal),
                )
            finally:
                await ws0.close()
                await ws1.close()

        (result, transcript), _ = asyncio.run(run())
        status = httpx.get(f"{server.http_base_url}/matches/{match['match_id']}").json()

    final_turn_result = transcript.match_transcript["turns"][-1]["result"]
    assert result == final_turn_result == {"result_type": "Win", "payload": {"seat": 0}}
    decoded = [json.loads(frame) for frame in frames]
    states = [frame["payload"] for frame in decoded if frame["type"] == "match_state"]
    assert states[-1]["lifecycle"] == "finished"
    assert states[-1]["result"] == final_turn_result
    assert all(state["result"] is None for state in states[:-1])
    assert status["result"] == final_turn_result


def test_a_seat_flooding_malformed_frames_is_closed() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as server:
        match = httpx.post(
            f"{server.http_base_url}/matches",
            json={"game_id": "tictactoe", "disconnect_grace_ms": 200},
        ).json()

        async def hello(ws: Any, seat: int) -> None:
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "schema_version": 4,
                        "seat": seat,
                        "payload": {
                            "client_name": "flood",
                            "client_version": "0",
                            "supported_schema_versions": [4],
                            "auth": None,
                            "requested_seat": seat,
                            "resume_token": None,
                        },
                    }
                )
            )

        async def run() -> tuple[int, int | None, str | None]:
            ws0 = await connect(match["seat_0_url"])
            ws1 = await connect(match["seat_1_url"])
            await hello(ws0, 0)
            await hello(ws1, 1)
            while json.loads(await ws0.recv())["type"] != "observation_request":
                pass
            errors = 0
            try:
                for _ in range(MAX_PROTOCOL_ERRORS_PER_TURN + 5):
                    await ws0.send("{not json")
                while True:
                    if json.loads(await ws0.recv())["type"] == "error":
                        errors += 1
            except ConnectionClosed as closed:
                received = closed.rcvd
                return errors, received.code if received else None, (
                    received.reason if received else None
                )
            finally:
                await ws1.close()

        errors, code, reason = asyncio.run(run())

    assert errors == MAX_PROTOCOL_ERRORS_PER_TURN
    assert (code, reason) == (4422, "too_many_malformed_frames")
