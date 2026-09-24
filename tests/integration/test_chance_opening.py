"""A game that opens at a chance node, over real WebSockets (Phase 37 Slice 3).

Before any seat acts, the opening flip is already a committed turn. The server
must broadcast it before the first ``match_state``; otherwise a client would
never learn an outcome it cannot recompute. Pig opens with a seat to move, so
this uses the coin fixture game from ``arena.testing.chance_factory``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from arena.games import build_default_registry
from arena.runtime.payloads import validate_runtime_transcript
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from arena.testing.chance_factory import build_coin_game_definition
from tests.integration._ws_client import connect, play_scripted
from tests.integration.conftest import RunningServer, serve


@pytest.fixture(scope="module")
def coin_server() -> Iterator[RunningServer]:
    registry = build_default_registry()
    registry.register(build_coin_game_definition())
    with serve(create_app(registry, rate_limiter=RateLimiter.unlimited())) as running:
        yield running


def _move(_: Any) -> dict[str, Any]:
    return {"type": "move"}


def test_opening_chance_turns_are_broadcast_before_play(coin_server: RunningServer) -> None:
    async def run() -> tuple[Any, list[str]]:
        resp = httpx.post(
            f"{coin_server.http_base_url}/matches",
            json={"game_id": "coin-game", "game_config": {"max_turns": 3}},
        )
        assert resp.status_code == 201, resp.text
        match = resp.json()
        frames: list[str] = []
        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            (_, transcript), _ = await asyncio.gather(
                play_scripted(ws0, 0, _move, frames=frames),
                play_scripted(ws1, 1, _move),
            )
        return transcript, frames

    transcript, frames = asyncio.run(asyncio.wait_for(run(), timeout=60))

    types = [json.loads(frame)["type"] for frame in frames]
    # welcome, then the opening flip, then the first match_state.
    assert types[:3] == ["welcome", "turn_committed", "match_state"]
    opening = json.loads(frames[1])["payload"]["turn_record"]
    assert opening["turn_index"] == 0
    assert opening["kind"] == "chance"
    assert opening["seat"] is None
    assert opening["outcome"]["face"] in (0, 1)

    turns = transcript.match_transcript["turns"]
    committed = [json.loads(f)["payload"]["turn_record"] for f in frames if '"turn_committed"' in f]
    assert [c["turn_index"] for c in committed] == list(range(len(turns)))

    validate_runtime_transcript(build_coin_game_definition(), transcript.model_dump(mode="json"))
