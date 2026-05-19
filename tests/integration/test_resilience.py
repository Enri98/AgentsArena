"""Integration tests: Phase 32 resilience features.

Tests:
1. Per-turn deadline expired → match_aborted with reason=turn_deadline_expired
2. Duplicate turn_id dropped (idempotency)
3. Mid-turn disconnect + reconnect within grace → match finishes normally
4. Mid-turn disconnect past grace → match_aborted with reason=peer_disconnected
5. Heartbeat timeout → WS closed with 4408 and peer receives match_aborted

Each test spins up a real uvicorn server (via module-scoped fixtures).
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
from arena.adapters.websocket.envelope import (
    ActionResponseEnvelope,
    HelloEnvelope,
)
from arena.adapters.websocket.messages import ActionResponseBody, HelloBody
from arena.server.app import create_app
from tests.integration._ws_client import (
    connect,
    recv_envelope,
    send_envelope,
)
from tests.integration.conftest import RunningServer

# ---------------------------------------------------------------------------
# Fast-heartbeat fixture (separate server instance for heartbeat test)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def running_server_fast_hb() -> RunningServer:  # type: ignore[return]
    """Server with 200 ms heartbeat interval and 2 max misses for fast testing."""
    port = _free_port()
    app = create_app(heartbeat_interval_ms=200, heartbeat_max_misses=2)
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _create_match(http_base: str, game_id: str = "tictactoe", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "game_id": game_id,
        "players": [{"label": "a"}, {"label": "b"}],
        **extra,
    }
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _hello_env(seat: int, resume_token: str | None = None) -> HelloEnvelope:
    return HelloEnvelope(
        schema_version=1,
        seat=seat,
        payload=HelloBody(
            client_name="test",
            client_version="0.1.0",
            supported_schema_versions=[1],
            auth=None,
            requested_seat=seat,
            resume_token=resume_token,
        ),
    )


def _action_env(
    seat: int, game_id: str, raw_action: dict[str, Any], match_id: str | None = None
) -> ActionResponseEnvelope:
    return ActionResponseEnvelope(
        schema_version=1,
        match_id=match_id,
        seat=seat,
        turn_id=str(uuid.uuid4()),
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id=game_id,
                schema_version=1,
                seat=seat,
                action=raw_action,
            )
        ),
    )


def _first_legal_tictactoe(obs_payload: Any) -> dict[str, Any]:
    legal = obs_payload.observation["legal_actions"]
    return {"row": legal[0]["row"], "column": legal[0]["column"]}


# ---------------------------------------------------------------------------
# Test 1: Per-turn deadline expired
# ---------------------------------------------------------------------------


def test_deadline_expired(running_server: RunningServer) -> None:
    """Server aborts the match when per_turn_deadline_ms elapses without action."""

    async def run() -> None:
        # Very short deadline: 200 ms.
        match = _create_match(
            running_server.http_base_url,
            per_turn_deadline_ms=200,
        )
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        async with await connect(seat_0_url) as ws0, await connect(seat_1_url) as ws1:
            await send_envelope(ws0, _hello_env(0))
            welcome0 = await recv_envelope(ws0)
            assert welcome0.type == "welcome"

            await send_envelope(ws1, _hello_env(1))
            welcome1 = await recv_envelope(ws1)
            assert welcome1.type == "welcome"

            # Drain initial match_state for both seats.
            ms0 = await recv_envelope(ws0)
            assert ms0.type == "match_state"
            ms1 = await recv_envelope(ws1)
            assert ms1.type == "match_state"

            # Seat 0 should receive observation_request (it moves first in tictactoe).
            obs0 = await recv_envelope(ws0)
            assert obs0.type == "observation_request", f"Expected obs_request, got {obs0.type}"

            # Neither seat sends an action — wait for the abort frames.
            # Give up to 5 s for the deadline + broadcast.
            from websockets.exceptions import ConnectionClosed as _CC

            async def drain_aborted(ws: Any) -> str | None:
                for _ in range(20):
                    try:
                        env = await asyncio.wait_for(recv_envelope(ws), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except _CC:
                        return None
                    if env.type == "match_aborted":
                        return env.payload.abort.reason  # type: ignore[union-attr]
                return None

            reason0 = await drain_aborted(ws0)
            assert reason0 == "turn_deadline_expired", f"seat0 got reason={reason0!r}"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 2: Duplicate turn_id dropped (idempotency)
# ---------------------------------------------------------------------------


def test_duplicate_turn_id_dropped(running_server: RunningServer) -> None:
    """Sending action_response twice with the same turn_id: second is silently dropped."""

    async def run() -> None:
        match = _create_match(running_server.http_base_url)
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        async with await connect(seat_0_url) as ws0, await connect(seat_1_url) as ws1:
            await send_envelope(ws0, _hello_env(0))
            welcome0 = await recv_envelope(ws0)
            assert welcome0.type == "welcome"
            game_id = welcome0.payload.game_id  # type: ignore[union-attr]

            await send_envelope(ws1, _hello_env(1))
            welcome1 = await recv_envelope(ws1)
            assert welcome1.type == "welcome"

            # Drain match_state for both.
            ms0 = await recv_envelope(ws0)
            assert ms0.type == "match_state"
            ms1 = await recv_envelope(ws1)
            assert ms1.type == "match_state"

            # Seat 0 gets observation_request.
            obs0 = await recv_envelope(ws0)
            assert obs0.type == "observation_request"

            obs_payload = obs0.payload.observation_request  # type: ignore[union-attr]
            raw_action = _first_legal_tictactoe(obs_payload)
            fixed_turn_id = str(uuid.uuid4())

            # Send the same action twice with the same turn_id.
            action_body = ActionResponseBody(
                action_response=ActionResponsePayload(
                    game_id=game_id,
                    schema_version=1,
                    seat=0,
                    action=raw_action,
                )
            )
            dup_env1 = ActionResponseEnvelope(
                schema_version=1,
                match_id=match["match_id"],
                seat=0,
                turn_id=fixed_turn_id,
                payload=action_body,
            )
            dup_env2 = ActionResponseEnvelope(
                schema_version=1,
                match_id=match["match_id"],
                seat=0,
                turn_id=fixed_turn_id,
                payload=action_body,
            )
            await send_envelope(ws0, dup_env1)
            await send_envelope(ws0, dup_env2)

            # The server should commit exactly one turn.
            # Drain frames until we see turn_committed.
            committed_count = 0
            for _ in range(10):
                try:
                    env = await asyncio.wait_for(recv_envelope(ws0), timeout=2.0)
                except asyncio.TimeoutError:
                    break
                if env.type == "turn_committed":
                    committed_count += 1
                elif env.type in ("match_finished", "match_aborted"):
                    break

            assert committed_count == 1, f"Expected 1 committed turn, got {committed_count}"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 3: Mid-turn disconnect + reconnect within grace
# ---------------------------------------------------------------------------


def test_reconnect_within_grace(running_server: RunningServer) -> None:
    """Seat 0 disconnects mid-turn and reconnects before grace expires; match finishes."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            disconnect_grace_ms=5000,  # 5 s grace
        )
        match_id = match["match_id"]
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        # Phase 1: connect both seats, get past the observation_request for seat 0.
        ws0_initial = await connect(seat_0_url)
        ws1 = await connect(seat_1_url)

        await send_envelope(ws0_initial, _hello_env(0))
        welcome0 = await recv_envelope(ws0_initial)
        assert welcome0.type == "welcome"
        resume_token = welcome0.payload.resume_token  # type: ignore[union-attr]
        game_id = welcome0.payload.game_id  # type: ignore[union-attr]

        await send_envelope(ws1, _hello_env(1))
        welcome1 = await recv_envelope(ws1)
        assert welcome1.type == "welcome"

        # Drain match_states.
        ms0 = await recv_envelope(ws0_initial)
        assert ms0.type == "match_state"
        ms1 = await recv_envelope(ws1)
        assert ms1.type == "match_state"

        # Seat 0 gets observation_request.
        obs0 = await recv_envelope(ws0_initial)
        assert obs0.type == "observation_request"

        # Abruptly close ws0 (simulates disconnect).
        await ws0_initial.close()

        # Reconnect seat 0 with its resume_token.
        ws0_new = await connect(seat_0_url)
        await send_envelope(ws0_new, _hello_env(0, resume_token=resume_token))

        welcome0_new = await recv_envelope(ws0_new)
        got_type = welcome0_new.type
        assert got_type == "welcome", f"Expected welcome on reconnect, got {got_type}"
        new_resume_token = welcome0_new.payload.resume_token  # type: ignore[union-attr]
        assert new_resume_token != resume_token, "Resume token should rotate after reconnect"

        # Drain match_state sent on reconnect.
        ms0_new = await recv_envelope(ws0_new)
        assert ms0_new.type == "match_state"

        # Server re-sends observation_request to the reconnected seat 0.
        obs0_new = await recv_envelope(ws0_new)
        assert obs0_new.type == "observation_request"

        # Now play both seats to completion.
        async def play_seat1() -> None:
            while True:
                try:
                    env = await asyncio.wait_for(recv_envelope(ws1), timeout=10.0)
                except asyncio.TimeoutError:
                    return
                if env.type in ("match_finished", "match_aborted"):
                    assert env.type == "match_finished", (
                        f"Expected match_finished, got match_aborted: "
                        f"{getattr(env.payload, 'abort', None)}"
                    )
                    return
                if env.type == "observation_request":
                    obs = env.payload.observation_request  # type: ignore[union-attr]
                    raw = _first_legal_tictactoe(obs)
                    await send_envelope(ws1, _action_env(1, game_id, raw, match_id))

        async def play_seat0() -> None:
            ws = ws0_new
            while True:
                try:
                    env = await asyncio.wait_for(recv_envelope(ws), timeout=10.0)
                except asyncio.TimeoutError:
                    return
                if env.type in ("match_finished", "match_aborted"):
                    assert env.type == "match_finished", (
                        f"Expected match_finished, got match_aborted: "
                        f"{getattr(env.payload, 'abort', None)}"
                    )
                    return
                if env.type == "observation_request":
                    obs = env.payload.observation_request  # type: ignore[union-attr]
                    raw = _first_legal_tictactoe(obs)
                    await send_envelope(ws, _action_env(0, game_id, raw, match_id))

        # First send seat 0's pending observation action, then play both.
        obs_payload0 = obs0_new.payload.observation_request  # type: ignore[union-attr]
        raw0 = _first_legal_tictactoe(obs_payload0)
        await send_envelope(ws0_new, _action_env(0, game_id, raw0, match_id))

        await asyncio.gather(play_seat0(), play_seat1())

        await ws0_new.close()
        await ws1.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 4: Mid-turn disconnect past grace → peer_disconnected
# ---------------------------------------------------------------------------


def test_disconnect_past_grace(running_server: RunningServer) -> None:
    """Seat 0 disconnects; grace expires → match_aborted with reason=peer_disconnected."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            disconnect_grace_ms=150,  # very short grace
        )
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        async with await connect(seat_0_url) as ws0, await connect(seat_1_url) as ws1:
            await send_envelope(ws0, _hello_env(0))
            welcome0 = await recv_envelope(ws0)
            assert welcome0.type == "welcome"

            await send_envelope(ws1, _hello_env(1))
            welcome1 = await recv_envelope(ws1)
            assert welcome1.type == "welcome"

            # Drain initial match_states.
            ms0 = await recv_envelope(ws0)
            assert ms0.type == "match_state"
            ms1 = await recv_envelope(ws1)
            assert ms1.type == "match_state"

            # Seat 0 gets observation_request then disconnects without acting.
            obs0 = await recv_envelope(ws0)
            assert obs0.type == "observation_request"
            await ws0.close()

            # Seat 1 should receive match_aborted after grace expires (≥150 ms).
            from websockets.exceptions import ConnectionClosed as _CC2

            async def drain_aborted(ws: Any) -> str | None:
                for _ in range(20):
                    try:
                        env = await asyncio.wait_for(recv_envelope(ws), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except _CC2:
                        return None
                    if env.type == "match_aborted":
                        return env.payload.abort.reason  # type: ignore[union-attr]
                return None

            reason1 = await drain_aborted(ws1)
            assert reason1 == "peer_disconnected", f"seat1 got reason={reason1!r}"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 5: Heartbeat timeout → 4408 close + match_aborted for peer
# ---------------------------------------------------------------------------


def test_heartbeat_timeout(running_server_fast_hb: RunningServer) -> None:
    """Seat 0 never responds to pings → closed 4408; seat 1 receives match_aborted."""
    from websockets.exceptions import ConnectionClosed

    async def run() -> None:
        match = _create_match(running_server_fast_hb.http_base_url)
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        # Seat 0: connect normally but ignore all pings (never send pong).
        ws0_raw = await connect(seat_0_url)
        ws1 = await connect(seat_1_url)

        await send_envelope(ws0_raw, _hello_env(0))
        welcome0 = await recv_envelope(ws0_raw)
        assert welcome0.type == "welcome"

        await send_envelope(ws1, _hello_env(1))
        welcome1 = await recv_envelope(ws1)
        assert welcome1.type == "welcome"

        # Drain initial match_states.
        ms0 = await recv_envelope(ws0_raw)
        assert ms0.type == "match_state"
        ms1 = await recv_envelope(ws1)
        assert ms1.type == "match_state"

        # Seat 0 receives observation_request but never acts or pongs.
        obs0 = await recv_envelope(ws0_raw)
        assert obs0.type == "observation_request"

        # Drain frames from seat 0 until we get ConnectionClosed with 4408.
        # Seat 1 must reply to application-level pings in parallel so its own
        # heartbeat does not time out before the server delivers match_aborted.
        from arena.adapters.websocket import WIRE_SCHEMA_VERSION
        from arena.adapters.websocket import dumps as _dumps
        from arena.adapters.websocket.envelope import PongEnvelope
        from arena.adapters.websocket.messages import PongBody

        async def _drain_ws0_until_close() -> int | None:
            while True:
                try:
                    raw = await asyncio.wait_for(ws0_raw.recv(), timeout=3.0)
                    # Got a ping (or other) frame — ignore it (no pong sent).
                    _ = raw
                except asyncio.TimeoutError:
                    return None
                except ConnectionClosed as exc:
                    return exc.rcvd.code if exc.rcvd else None
                except Exception:
                    return None

        async def drain_aborted_hb(ws: Any) -> str | None:
            """Drain ws1 frames, replying to pings, until match_aborted or closed."""
            for _ in range(30):
                try:
                    env = await asyncio.wait_for(recv_envelope(ws), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except ConnectionClosed:
                    return None
                if env.type == "ping":
                    # Reply with pong so seat 1's heartbeat doesn't time out.
                    nonce = env.payload.nonce  # type: ignore[union-attr]
                    pong = PongEnvelope(
                        schema_version=WIRE_SCHEMA_VERSION,
                        match_id=env.match_id,
                        payload=PongBody(nonce=nonce),
                    )
                    try:
                        await ws.send(_dumps(pong))
                    except Exception:
                        pass
                    continue
                if env.type == "match_aborted":
                    return env.payload.abort.reason  # type: ignore[union-attr]
            return None

        # Run both drains concurrently so ws1 can reply to pings while we
        # wait for ws0 to be closed by the heartbeat timeout.
        close_code, reason1 = await asyncio.gather(
            _drain_ws0_until_close(),
            drain_aborted_hb(ws1),
        )

        assert close_code == 4408, f"Expected close code 4408, got {close_code}"
        assert reason1 == "heartbeat_timeout", f"seat1 got reason={reason1!r}"

        try:
            await ws1.close()
        except Exception:
            pass

    asyncio.run(run())
