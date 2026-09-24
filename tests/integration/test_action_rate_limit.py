"""Protocol §13 per-match action cap, enforced on the real wire.

The three connection/creation caps landed in Phase 36 Slice 0. This one is
enforced inside the turn loop, so it landed with the Slice 2 transport work.

Exceeding it closes the offending connection with 4429. No new abort reason is
introduced: the closed socket surfaces as a disconnect and the existing
disconnect-grace path decides the match outcome.

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
import websockets

from arena.adapters.in_process import ActionResponsePayload
from arena.adapters.websocket.envelope import ActionResponseEnvelope, HelloEnvelope
from arena.adapters.websocket.messages import ActionResponseBody, HelloBody
from arena.server.app import create_app
from arena.server.rate_limits import CLOSE_RATE_LIMITED, RateLimiter
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
            supported_schema_versions=[1, 2, 3],
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


def test_action_flood_closes_the_offending_seat_with_4429(
    running_server_tight_actions: RunningServer,
) -> None:
    """A seat exceeding the per-match action rate is shed with 4429."""

    async def run() -> None:
        match = _create_match(
            running_server_tight_actions.http_base_url,
            per_turn_deadline_ms=10_000,
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
            # stays active and the loop keeps reading its frames. A legal action
            # would pass the turn to seat 1 after the first send, and seat 0's
            # remaining frames would never be read.
            for _ in range(5):
                await send_envelope(ws0, _action(0, 99))

            # Seat 0's socket is closed with 4429 once the cap trips. Reading
            # drains whatever was already in flight first.
            with pytest.raises(websockets.exceptions.ConnectionClosed) as exc:
                for _ in range(20):
                    await recv_envelope(ws0)

            assert exc.value.rcvd is not None
            assert exc.value.rcvd.code == CLOSE_RATE_LIMITED

    asyncio.run(asyncio.wait_for(run(), timeout=30))
