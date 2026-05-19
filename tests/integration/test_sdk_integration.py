"""Integration tests for arena.sdk against a real uvicorn server.

These tests exercise the SDK's public API (callback form via `connect()` and
loop form via `Session`) end-to-end over real TCP WebSocket connections.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from arena.games import build_default_registry
from arena.runtime.payloads import validate_runtime_transcript
from arena.sdk import Session, connect
from arena.sdk._events import (
    MatchAbortedEvent,
    MatchFinishedEvent,
    MatchStateEvent,
    ObservationEvent,
    TurnCommittedEvent,
)
from tests.integration.conftest import RunningServer

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


def test_sdk_connect_callback_connect4(running_server: RunningServer) -> None:
    """SDK callback form (`connect()`) drives a full Connect 4 match."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "alice"}, {"label": "bob"}],
        )
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        def choose_connect4(obs: Any) -> dict[str, Any]:
            legal = obs.observation["legal_actions"]
            return {"column": legal[0]["column"]}

        (result_0, transcript_0), (result_1, transcript_1) = await asyncio.gather(
            connect(seat_0_url, 0, choose_connect4),
            connect(seat_1_url, 1, choose_connect4),
        )

        assert transcript_0 is not None
        assert transcript_1 is not None

        registry = build_default_registry()
        definition = registry.get("connect4")
        loaded = validate_runtime_transcript(definition, transcript_0.model_dump(mode="json"))
        assert loaded is not None

        assert transcript_0.lifecycle == "finished"

    asyncio.run(run())


def test_sdk_session_loop_tictactoe(running_server: RunningServer) -> None:
    """SDK loop form (`Session`) drives a full Tic-Tac-Toe match."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "tictactoe",
            players=[{"label": "x"}, {"label": "o"}],
        )
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        async def play_seat(url: str, seat: int) -> tuple[Any, Any]:
            async with await Session.connect(url, seat) as session:
                while True:
                    event = await session.recv()

                    if isinstance(event, ObservationEvent):
                        legal = event.body.observation_request.observation["legal_actions"]
                        action = {"row": legal[0]["row"], "column": legal[0]["column"]}
                        await session.send_action(action)

                    elif isinstance(event, MatchFinishedEvent):
                        return event.body.result, event.body.transcript

                    elif isinstance(event, MatchAbortedEvent):
                        raise RuntimeError(
                            f"Match aborted for seat {seat}: {event.body.abort}"
                        )

                    elif isinstance(event, (MatchStateEvent, TurnCommittedEvent)):
                        continue

        (result_0, transcript_0), (result_1, transcript_1) = await asyncio.gather(
            play_seat(seat_0_url, 0),
            play_seat(seat_1_url, 1),
        )

        assert transcript_0 is not None
        assert transcript_1 is not None
        assert transcript_0.lifecycle == "finished"
        assert transcript_1.lifecycle == "finished"

    asyncio.run(run())


def test_sdk_session_properties(running_server: RunningServer) -> None:
    """Session exposes match_id, seat, game_id, and welcome after connecting."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "alice"}, {"label": "bob"}],
        )
        seat_0_url = match["seat_0_url"]

        session = await Session.connect(seat_0_url, 0)
        try:
            assert session.match_id == match["match_id"]
            assert session.seat == 0
            assert session.game_id == "connect4"
            assert session.welcome is not None
            assert session.welcome.game_id == "connect4"
        finally:
            await session.close()

    asyncio.run(run())
