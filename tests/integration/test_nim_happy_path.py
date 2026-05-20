"""Integration test: Nim match via real TCP WebSocket frames.

Seat 0 plays nim-sum optimal strategy (leaves nim-sum=0 for opponent whenever
possible). Seat 1 always picks the first legal action (deterministic).
Seat 0 should win from the default starting position (3 piles of 7, nim-sum=7^7^7=7≠0).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from arena.games import build_default_registry
from arena.runtime.payloads import validate_runtime_transcript
from tests.integration._ws_client import connect, play_scripted
from tests.integration.conftest import RunningServer


def _nim_sum_action(obs_payload: Any) -> dict[str, Any]:
    """Nim-sum optimal: find a move that makes XOR of all piles equal to 0."""
    piles: list[int] = list(obs_payload.observation["piles"])
    legal = obs_payload.observation["legal_actions"]

    # Try each legal action; pick one that leaves nim-sum == 0
    for action in legal:
        idx = action["pile_index"]
        cnt = action["count"]
        new_piles = list(piles)
        new_piles[idx] -= cnt
        nim_sum = 0
        for p in new_piles:
            nim_sum ^= p
        if nim_sum == 0:
            return {"pile_index": idx, "count": cnt}

    # No winning move available; take 1 from the largest non-empty pile
    best = max(legal, key=lambda a: piles[a["pile_index"]])
    return {"pile_index": best["pile_index"], "count": 1}


def _first_legal_nim(obs_payload: Any) -> dict[str, Any]:
    legal = obs_payload.observation["legal_actions"]
    a = legal[0]
    return {"pile_index": a["pile_index"], "count": a["count"]}


def _create_match(http_base: str, game_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"game_id": game_id, **extra}
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_nim_happy_path(running_server: RunningServer) -> None:
    """Two scripted seats complete a Nim match via real TCP WebSocket frames."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "nim",
            players=[{"label": "optimal"}, {"label": "first-legal"}],
        )
        seat_0_url = match["seat_0_url"]
        seat_1_url = match["seat_1_url"]

        async with await connect(seat_0_url) as ws0, await connect(seat_1_url) as ws1:
            (_, transcript_0), (_, transcript_1) = await asyncio.gather(
                play_scripted(ws0, 0, _nim_sum_action),
                play_scripted(ws1, 1, _first_legal_nim),
            )

        registry = build_default_registry()
        definition = registry.get("nim")

        assert transcript_0 is not None
        assert transcript_1 is not None

        loaded = validate_runtime_transcript(definition, transcript_0.model_dump(mode="json"))
        assert loaded is not None

        assert transcript_0.lifecycle == "finished"
        assert transcript_1.lifecycle == "finished"

    asyncio.run(run())
