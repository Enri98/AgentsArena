"""Protocol §13 per-match action cap, enforced on the real wire.

The three connection/creation caps landed in Phase 36 Slice 0. This one is
enforced inside the turn loop, so it landed with the Slice 2 transport work.

Exceeding it no longer closes the connection (Phase 38 hardening): the server
delays reading the next action until the window has room. A scripted or fast
bot legitimately plays faster than any per-second cap, and closing it with
4429 aborted the match as peer_disconnected, blaming an innocent seat.

Scope note: the cap counts action frames the server actually *reads*, which are
the ones from the seat whose turn it is. An off-turn seat's frames sit unread in
its socket buffer until its turn arrives, so they are not counted when sent. The
cap therefore bounds work the match loop performs, not raw inbound traffic; the
per-IP and per-match connection caps are what bound the latter.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import uuid
from typing import Any

import httpx
import pytest
import uvicorn

from arena.adapters.in_process import ActionResponsePayload
from arena.adapters.websocket.envelope import ActionResponseEnvelope, HelloEnvelope
from arena.adapters.websocket.messages import ActionResponseBody, HelloBody
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration._ws_client import connect, recv_envelope, send_envelope
from tests.integration.conftest import RunningServer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def running_server_tight_actions() -> RunningServer:  # type: ignore[return]
    """Server allowing a single action per match per second."""

    port = _free_port()
    app = create_app(
        rate_limiter=RateLimiter(
            max_actions_per_match_per_sec=1,
            max_ws_connections_per_ip=99,
            max_connections_per_match=99,
            max_match_creations_per_ip_per_min=99,
        )
    )
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws="websockets-sansio",
        ws_ping_interval=None,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10.0
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            thread.join(timeout=5)
            raise RuntimeError(f"uvicorn server did not start within 10 s on port {port}")
        time.sleep(0.05)

    yield RunningServer(
        http_base_url=f"http://127.0.0.1:{port}",
        ws_base_url=f"ws://127.0.0.1:{port}",
    )

    server.should_exit = True
    thread.join(timeout=10)


def _hello(seat: int) -> HelloEnvelope:
    return HelloEnvelope(
        schema_version=1,
        seat=seat,
        payload=HelloBody(
            client_name="test",
            client_version="0.1.0",
            supported_schema_versions=[1, 2, 3, 4],
            auth=None,
            requested_seat=seat,
            resume_token=None,
        ),
    )


def _action(seat: int, column: int) -> ActionResponseEnvelope:
    """Column 99 is off the board, so the action is rejected but the turn holds."""

    return ActionResponseEnvelope(
        schema_version=1,
        seat=seat,
        turn_id=str(uuid.uuid4()),
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id="connect4",
                schema_version=1,
                seat=seat,
                action={"column": column},
            )
        ),
    )


def _create_match(http_base: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"game_id": "connect4", **extra}
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_an_action_flood_is_throttled_not_disconnected(
    running_server_tight_actions: RunningServer,
) -> None:
    """A seat exceeding the per-match action rate is slowed down, not shed.

    With a cap of 1 per second, five rejected actions sent at once are read about
    one second apart, and the connection stays open.
    """

    async def run() -> list[float]:
        match = _create_match(
            running_server_tight_actions.http_base_url,
            per_turn_deadline_ms=20_000,
            disconnect_grace_ms=500,
            # A generous retry budget keeps seat 0 active across several
            # rejected actions, so the loop keeps reading from it.
            per_action_retry_budget=10,
        )

        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            await send_envelope(ws0, _hello(0))
            assert (await recv_envelope(ws0)).type == "welcome"
            await send_envelope(ws1, _hello(1))
            assert (await recv_envelope(ws1)).type == "welcome"

            assert (await recv_envelope(ws0)).type == "match_state"
            assert (await recv_envelope(ws1)).type == "match_state"
            assert (await recv_envelope(ws0)).type == "observation_request"

            # Illegal actions are rejected without ending the turn, so seat 0
            # stays active and the loop keeps reading its frames.
            for _ in range(3):
                await send_envelope(ws0, _action(0, 99))

            stamps: list[float] = []
            while len(stamps) < 3:
                env = await asyncio.wait_for(recv_envelope(ws0), timeout=10)
                assert env.type == "action_rejected", env.type
                stamps.append(time.monotonic())
            return stamps

    stamps = asyncio.run(asyncio.wait_for(run(), timeout=30))
    # Read at most once per second: the three rejections span about two seconds.
    assert stamps[-1] - stamps[0] >= 1.5
