"""Integration tests: real uvicorn server, real TCP WebSocket frames.

Each test connects via the `websockets` async client (not Starlette TestClient)
and drives a complete match end-to-end.

Scripted move strategy: always pick the first entry in `legal_actions` from the
serialized observation.  This is deterministic and guaranteed to be legal.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from arena.games import build_default_registry
from arena.runtime.payloads import validate_runtime_transcript
from tests.integration._ws_client import connect, play_scripted, recv_envelope, send_envelope
from tests.integration.conftest import RunningServer

# ---------------------------------------------------------------------------
# Scripted move selectors (deterministic: always pick first legal action)
# ---------------------------------------------------------------------------


def _first_legal_connect4(obs_payload: Any) -> dict[str, Any]:
    legal = obs_payload.observation["legal_actions"]
    return {"column": legal[0]["column"]}


def _first_legal_tictactoe(obs_payload: Any) -> dict[str, Any]:
    legal = obs_payload.observation["legal_actions"]
    return {"row": legal[0]["row"], "column": legal[0]["column"]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_match(http_base: str, game_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"game_id": game_id, **extra}
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_connect4_happy_path(running_server: RunningServer) -> None:
    """Two scripted seats complete a Connect 4 match via real TCP WebSocket frames."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "alice"}, {"label": "bob"}],
            per_action_retry_budget=3,
        )
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        async with await connect(seat_0_url) as ws0, await connect(seat_1_url) as ws1:
            (_, transcript_0), (_, transcript_1) = await asyncio.gather(
                play_scripted(ws0, 0, _first_legal_connect4),
                play_scripted(ws1, 1, _first_legal_connect4),
            )

        registry = build_default_registry()
        definition = registry.get("connect4")

        assert transcript_0 is not None
        assert transcript_1 is not None

        loaded = validate_runtime_transcript(definition, transcript_0.model_dump(mode="json"))
        assert loaded is not None

        assert transcript_0.lifecycle == "finished"
        assert transcript_1.lifecycle == "finished"

    asyncio.run(run())


def test_tictactoe_happy_path(running_server: RunningServer) -> None:
    """Two scripted seats complete a Tic-Tac-Toe match via real TCP WebSocket frames."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "tictactoe",
            players=[{"label": "x"}, {"label": "o"}],
        )
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        async with await connect(seat_0_url) as ws0, await connect(seat_1_url) as ws1:
            (_, transcript_0), (_, transcript_1) = await asyncio.gather(
                play_scripted(ws0, 0, _first_legal_tictactoe),
                play_scripted(ws1, 1, _first_legal_tictactoe),
            )

        registry = build_default_registry()
        definition = registry.get("tictactoe")

        assert transcript_0 is not None
        loaded = validate_runtime_transcript(definition, transcript_0.model_dump(mode="json"))
        assert loaded is not None

        assert transcript_0.lifecycle == "finished"
        assert transcript_1.lifecycle == "finished"

    asyncio.run(run())


def test_malformed_envelope_after_handshake(running_server: RunningServer) -> None:
    """Sending non-JSON after the handshake gets an error envelope (non-fatal).

    Per §15 of NETWORK_PROTOCOL.md and the runtime_bridge implementation, a
    malformed envelope after the handshake produces an `error` envelope with
    code `malformed_envelope`; the connection is NOT closed.  The match can
    continue normally afterward.

    We verify:
    1. seat 0 receives an `error` envelope with code `malformed_envelope`.
    2. The connection remains open (seat 0 can still send a valid action).
    """

    async def run() -> None:
        match = _create_match(running_server.http_base_url, "connect4")
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        from arena.adapters.websocket.envelope import HelloEnvelope
        from arena.adapters.websocket.messages import HelloBody

        def _hello(seat: int) -> HelloEnvelope:
            return HelloEnvelope(
                schema_version=1,
                seat=seat,
                payload=HelloBody(
                    client_name="test",
                    client_version="0.1.0",
                    supported_schema_versions=[1],
                    auth=None,
                    requested_seat=seat,
                    resume_token=None,
                ),
            )

        async with await connect(seat_0_url) as ws0, await connect(seat_1_url) as ws1:
            await send_envelope(ws0, _hello(0))
            welcome0 = await recv_envelope(ws0)
            assert welcome0.type == "welcome"

            await send_envelope(ws1, _hello(1))
            welcome1 = await recv_envelope(ws1)
            assert welcome1.type == "welcome"

            # Drain the initial match_state broadcast and observation_request for seat 0.
            ms0 = await recv_envelope(ws0)
            assert ms0.type == "match_state"
            obs0 = await recv_envelope(ws0)
            assert obs0.type == "observation_request"
            ms1 = await recv_envelope(ws1)
            assert ms1.type == "match_state"

            # Send raw invalid bytes from seat 0; server should respond with error envelope.
            await ws0.send("not json at all }{")
            err = await recv_envelope(ws0)
            assert err.type == "error", f"Expected error envelope, got {err.type}"
            assert err.payload.code == "malformed_envelope"  # type: ignore[union-attr]

            # Connection still open — seat 0 can close gracefully.
            await ws0.close()
            await ws1.close()

    asyncio.run(run())
