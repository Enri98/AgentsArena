"""Integration test: Pig — a game with chance nodes — over real TCP WebSockets.

This is the end-to-end proof of Phase 37:

* every committed turn reaches the clients, including each die roll, which a
  client cannot recompute;
* the transcript validates by replaying recorded outcomes, with no seed;
* the same seed and the same choices reproduce the same match through the server;
* **the seed appears in no frame either seat or a spectator receives.**

The server runs in-process (see ``conftest.py``), so the seed it mints is pinned
by patching ``arena.match.local_match._mint_seed``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import websockets

from arena.games import build_default_registry
from arena.runtime.payloads import validate_runtime_transcript
from tests.integration._ws_client import connect, play_scripted, send_envelope
from tests.integration.conftest import RunningServer
from tests.integration.test_spectator import _spectator_hello

SEED = 0x9F1C_2B3A_7D6E_5F40_1122_3344_5566_7788
TARGET = 20


def _hold_at_ten(obs_payload: Any) -> dict[str, Any]:
    """Roll until the turn total reaches 10, then hold."""

    observation = obs_payload.observation
    choices = [a["choice"] for a in observation["legal_actions"]]
    if "hold" in choices and observation["turn_total"] >= 10:
        return {"choice": "hold"}
    return {"choice": "roll"}


def _create_match(http_base: str) -> dict[str, Any]:
    resp = httpx.post(
        f"{http_base}/matches",
        json={
            "game_id": "pig",
            "players": [{"label": "a"}, {"label": "b"}],
            "game_config": {"target_score": TARGET},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _attach_spectator(ws: Any) -> str:
    """Complete the spectator handshake, so no committed turn can be missed."""

    await send_envelope(ws, _spectator_hello())
    raw = await ws.recv()
    welcome = raw if isinstance(raw, str) else raw.decode()
    assert json.loads(welcome)["type"] == "spectator_welcome"
    return welcome


async def _spectate(ws: Any, welcome: str) -> list[str]:
    frames: list[str] = [welcome]
    try:
        while True:
            raw = await ws.recv()
            frames.append(raw if isinstance(raw, str) else raw.decode())
    except websockets.exceptions.ConnectionClosed:
        pass
    return frames


async def _play_one(running_server: RunningServer) -> dict[str, Any]:
    match = _create_match(running_server.http_base_url)
    spectate_url = f"{running_server.ws_base_url}/matches/{match['match_id']}/spectate"
    frames_0: list[str] = []
    frames_1: list[str] = []

    async with (
        await connect(match["seat_0_url"]) as ws0,
        await connect(match["seat_1_url"]) as ws1,
        await connect(spectate_url) as spec,
    ):
        welcome = await _attach_spectator(spec)
        spectator = asyncio.create_task(_spectate(spec, welcome))
        (_, transcript_0), (_, transcript_1) = await asyncio.gather(
            play_scripted(ws0, 0, _hold_at_ten, frames=frames_0),
            play_scripted(ws1, 1, _hold_at_ten, frames=frames_1),
        )
        spectator_frames = await asyncio.wait_for(spectator, timeout=10)

    return {
        "transcript_0": transcript_0,
        "transcript_1": transcript_1,
        "frames": {"seat_0": frames_0, "seat_1": frames_1, "spectator": spectator_frames},
    }


@pytest.fixture
def pinned_seed(monkeypatch: pytest.MonkeyPatch) -> int:
    import arena.match.local_match as local_match

    monkeypatch.setattr(local_match, "_mint_seed", lambda: SEED)
    return SEED


def test_pig_over_the_wire(running_server: RunningServer, pinned_seed: int) -> None:
    result = asyncio.run(asyncio.wait_for(_play_one(running_server), timeout=60))

    transcript = result["transcript_0"]
    assert transcript.lifecycle == "finished"
    assert result["transcript_1"].lifecycle == "finished"

    # Replay applies recorded rolls; validation needs no seed.
    definition = build_default_registry().get("pig")
    validate_runtime_transcript(definition, transcript.model_dump(mode="json"))

    turns = transcript.match_transcript["turns"]
    kinds = [turn["kind"] for turn in turns]
    assert "chance" in kinds and "action" in kinds
    for turn in turns:
        if turn["kind"] == "chance":
            assert turn["seat"] is None and turn["action"] is None
            assert 1 <= turn["outcome"]["face"] <= 6

    # Every committed turn reached each client, in order — including the roll
    # that follows each "roll" action in the same step.
    for name, frames in result["frames"].items():
        committed = [
            json.loads(frame)["payload"]["turn_record"]
            for frame in frames
            if json.loads(frame)["type"] == "turn_committed"
        ]
        assert [record["turn_index"] for record in committed] == list(range(len(turns))), name
        assert [record["kind"] for record in committed] == kinds, name
        for record, turn in zip(committed, turns):
            assert record["outcome"] == turn["outcome"], name


def test_the_seed_never_reaches_a_client(
    running_server: RunningServer, pinned_seed: int
) -> None:
    result = asyncio.run(asyncio.wait_for(_play_one(running_server), timeout=60))

    fragments = [str(pinned_seed), f"{pinned_seed:x}", f"{pinned_seed:X}"]
    for name, frames in result["frames"].items():
        assert frames, name
        text = "\n".join(frames)
        for fragment in fragments:
            assert fragment not in text, f"seed visible to {name}"
        for frame in frames:
            assert '"seed"' not in frame, f"a seed field reached {name}"


def test_the_same_seed_reproduces_the_match_through_the_server(
    running_server: RunningServer, pinned_seed: int
) -> None:
    first = asyncio.run(asyncio.wait_for(_play_one(running_server), timeout=60))
    second = asyncio.run(asyncio.wait_for(_play_one(running_server), timeout=60))

    assert (
        first["transcript_0"].match_transcript["turns"]
        == second["transcript_0"].match_transcript["turns"]
    )


def test_seatless_chance_turns_do_not_confuse_the_spectator_stream(
    running_server: RunningServer, pinned_seed: int
) -> None:
    result = asyncio.run(asyncio.wait_for(_play_one(running_server), timeout=60))
    types = [json.loads(frame)["type"] for frame in result["frames"]["spectator"]]
    assert "observation_request" not in types
    assert types[-1] == "match_finished"



def _always_roll(_: Any) -> dict[str, Any]:
    return {"choice": "roll"}


def test_a_match_that_never_ends_is_capped_by_the_server() -> None:
    """Two seats that only roll never bank a point; the server bounds the match.

    Found by adversarial review of Phase 37: without a cap, one client holding
    both seat URLs could grow a transcript without limit.
    """

    from arena.server.app import create_app
    from arena.server.rate_limits import RateLimiter
    from tests.integration.conftest import serve

    app = create_app(rate_limiter=RateLimiter.unlimited(), max_turns_per_match=40)

    async def run(server: RunningServer) -> Any:
        match = _create_match(server.http_base_url)
        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            results = await asyncio.gather(
                play_scripted(ws0, 0, _always_roll),
                play_scripted(ws1, 1, _always_roll),
                return_exceptions=True,
            )
        return results

    with serve(app) as server:
        results = asyncio.run(asyncio.wait_for(run(server), timeout=60))

    for outcome in results:
        assert isinstance(outcome, RuntimeError)
        assert "turn_limit_exceeded" in str(outcome)
