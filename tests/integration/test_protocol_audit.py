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
from structlog.testing import capture_logs
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
    """And the log stays bounded: the server stops reading at the cap, though
    thousands of frames may already be buffered."""

    app = create_app(rate_limiter=RateLimiter.unlimited())
    with capture_logs() as logs, serve(app) as server:
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
                for _ in range(2000):
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
    events = [entry["event"] for entry in logs]
    assert events.count("protocol_violation") == MAX_PROTOCOL_ERRORS_PER_TURN
    assert events.count("outbox_overflow") == 0


def test_a_spectator_that_stops_reading_is_dropped_on_a_real_server(
    monkeypatch: Any,
) -> None:
    """uvicorn's sansio WebSocket never blocks a send, so the outbox of a reader
    that stopped never fills; the transport's unsent bytes are the signal. The
    bound is lowered, and the client's receive buffer made small, so a short
    match crosses it on any platform (Linux loopback buffers hold megabytes)."""

    import socket

    from websockets.asyncio.client import connect as ws_connect

    import arena.server.runtime_bridge as bridge

    monkeypatch.setattr(bridge, "MAX_SEND_BACKLOG_BYTES", 64 * 1024)
    app = create_app(rate_limiter=RateLimiter.unlimited(), max_turns_per_match=3000)
    with capture_logs() as logs, serve(app) as server:
        match = httpx.post(f"{server.http_base_url}/matches", json={"game_id": "pig"}).json()
        spectate_url = f"{server.ws_base_url}/matches/{match['match_id']}/spectate"

        def always_roll(payload: Any) -> dict[str, Any]:
            return {"choice": "roll"}

        async def run() -> tuple[int | None, str | None]:
            # max_queue=1: the client stops reading the socket once one frame
            # waits; a small receive buffer makes the server's transport back up.
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            port = int(server.http_base_url.rsplit(":", 1)[1])
            sock.connect(("127.0.0.1", port))
            spectator = await ws_connect(
                spectate_url, sock=sock, ping_interval=None, max_queue=1
            )
            await spectator.send(
                json.dumps(
                    {
                        "type": "spectator_hello",
                        "schema_version": 4,
                        "payload": {
                            "client_name": "slow",
                            "client_version": "0",
                            "supported_schema_versions": [4],
                        },
                    }
                )
            )
            await spectator.recv()  # the welcome; then read nothing while it plays
            ws0 = await connect(match["seat_0_url"])
            ws1 = await connect(match["seat_1_url"])
            try:
                await asyncio.gather(
                    play_scripted(ws0, 0, always_roll),
                    play_scripted(ws1, 1, always_roll),
                    return_exceptions=True,  # the match aborts at the turn cap
                )
            finally:
                await ws0.close()
                await ws1.close()
            try:
                while True:
                    await spectator.recv()
            except ConnectionClosed as closed:
                received = closed.rcvd
                return (received.code, received.reason) if received else (None, None)

        code, reason = asyncio.run(run())

    events = [entry["event"] for entry in logs]
    assert "spectator_dropped" in events
    # Its close frame may be lost behind the unsent backlog; it was never let
    # run to the normal end.
    assert (code, reason) in ((1000, "spectator_too_slow"), (None, None))
