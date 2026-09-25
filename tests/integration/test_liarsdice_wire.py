"""Liar's Dice over real TCP: the Phase 39 acceptance criteria.

* Neither seat observes the other's dice at any point before a showdown reveals
  them: live frames, observation requests, reconnect replay, and the final
  transcript. Checked structurally (``leaked_hand_paths``) and against ground
  truth from the server's full transcript.
* A spectator sees the bid history and the reveal, never a hand mid-round.
* Two matches that differ only in seat 1's opening hand look identical to seat 0
  and to a spectator until the first showdown.
* The server's full transcript replays exactly, opening roll included.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import websockets

from arena.adapters.websocket import dumps
from arena.core.chance import ChanceRng
from arena.games.liarsdice.audit import leaked_hand_paths
from arena.runtime.payloads import dump_runtime_transcript, validate_runtime_transcript
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration._ws_client import connect, play_scripted, send_envelope
from tests.integration.conftest import RunningServer, serve
from tests.integration.test_hidden_information import (
    _PER_MATCH_KEYS,
    _hello,
    _until,
)
from tests.integration.test_spectator import _spectator_hello

DICE = 3


@pytest.fixture(scope="module")
def ld_server() -> Iterator[tuple[RunningServer, Any]]:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as running:
        yield running, app


def _script(moves: list[dict[str, Any]]):
    """Replay fixed moves, then always call (or open with the lowest bid)."""

    queue = list(moves)

    def choose(request: Any) -> dict[str, Any]:
        legal = request.observation["legal_actions"]
        while queue:
            move = queue.pop(0)
            if move in legal:
                return move
        return legal[0]  # Call when possible; otherwise the lowest bid

    return choose


def _create(server: RunningServer) -> dict:
    resp = httpx.post(
        f"{server.http_base_url}/matches",
        json={
            "game_id": "liarsdice",
            "game_config": {"dice_per_seat": DICE},
            "supported_schema_versions": [4],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _drain(ws: Any) -> list[str]:
    frames: list[str] = []
    try:
        while True:
            raw = await ws.recv()
            frames.append(raw if isinstance(raw, str) else raw.decode())
    except websockets.exceptions.ConnectionClosed:
        pass
    return frames


async def _play(server: RunningServer, moves0: list, moves1: list) -> dict:
    match = _create(server)
    spectate_url = f"{server.ws_base_url}/matches/{match['match_id']}/spectate"
    frames: dict[str, list[str]] = {"seat_0": [], "seat_1": []}
    async with (
        await connect(match["seat_0_url"]) as ws0,
        await connect(match["seat_1_url"]) as ws1,
        await connect(spectate_url) as spec,
    ):
        await send_envelope(spec, _spectator_hello())
        welcome = await spec.recv()
        spectator = asyncio.create_task(_drain(spec))
        await asyncio.gather(
            play_scripted(ws0, 0, _script(moves0), frames=frames["seat_0"]),
            play_scripted(ws1, 1, _script(moves1), frames=frames["seat_1"]),
        )
        frames["spectator"] = [welcome, *await asyncio.wait_for(spectator, timeout=10)]
    return {"match_id": match["match_id"], "frames": frames}


def _full(app: Any, match_id: str) -> dict:
    return dump_runtime_transcript(app.state.match_registry.get(match_id).session)


def _state_views(value: Any) -> list[dict]:
    """Every dict carrying a hand and its round: seat state views and observations."""

    found: list[dict] = []
    if isinstance(value, dict):
        if "my_dice" in value and "round_number" in value:
            found.append(value)
        for item in value.values():
            found.extend(_state_views(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_state_views(item))
    return found


def _hands_by_round(full: dict) -> list[list[list[int]]]:
    return [
        turn["outcome"]["dice"]
        for turn in full["match_transcript"]["turns"]
        if turn["kind"] == "chance"
    ]


def test_no_client_ever_sees_a_hand_it_may_not(ld_server) -> None:
    server, app = ld_server
    played = asyncio.run(asyncio.wait_for(_play(server, [], []), timeout=60))
    full = _full(app, played["match_id"])
    hands = _hands_by_round(full)
    assert len(hands) >= DICE  # several rounds: re-rolls after reveals

    for name, viewer in (("seat_0", 0), ("seat_1", 1), ("spectator", None)):
        for raw in played["frames"][name]:
            frame = json.loads(raw)
            assert leaked_hand_paths(frame, viewer) == [], (name, frame["type"])

    # Ground truth: every hand a seat is shown is its own, for the current round.
    for name, viewer in (("seat_0", 0), ("seat_1", 1)):
        shown = []
        for raw in played["frames"][name]:
            frame = json.loads(raw)
            committed = frame["type"] == "turn_committed"
            record = frame["payload"]["turn_record"] if committed else None
            if record is not None and record["kind"] == "chance":
                shown.append(record["outcome"]["my_dice"])
            # Every state view anywhere in the frame (live snapshots, the
            # observation, each turn of the final transcript) names its round:
            # its hand must be exactly this seat's hand for that round.
            for view in _state_views(frame):
                if view["my_dice"]:
                    assert view["my_dice"] == hands[view["round_number"] - 1][viewer], name
        assert shown == [h[viewer] for h in hands], name

    # The spectator saw the bids and every reveal.
    spectator = [json.loads(f) for f in played["frames"]["spectator"]]
    events = [
        e["event_type"]
        for f in spectator
        if f["type"] == "turn_committed"
        for e in f["payload"]["events"]
    ]
    assert "BidMade" in events
    assert events.count("BidCalled") == len(hands)

    # The server's full transcript replays exactly, opening roll included.
    definition = app.state.match_registry.get(played["match_id"]).session.definition
    validate_runtime_transcript(definition, full)


def _seeds_differing_only_in_seat_1() -> tuple[int, int]:
    def opening(seed: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
        rng = ChanceRng(seed=seed)
        first, rng = rng.draw_many(6, DICE)
        second, _ = rng.draw_many(6, DICE)
        return first, second

    base = opening(1)
    for seed in range(2, 20_000):
        candidate = opening(seed)
        if candidate[0] == base[0] and candidate[1] != base[1]:
            return 1, seed
    raise AssertionError("no seed pair")  # pragma: no cover


def _prefix_until_reveal(frames: list[str]) -> list[Any]:
    out = []
    for raw in frames:
        frame = json.loads(raw)
        if frame["type"] == "turn_committed" and any(
            e["event_type"] == "BidCalled" for e in frame["payload"]["events"]
        ):
            break
        out.append(_strip(frame))
    return out


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in _PER_MATCH_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def test_seat_0_cannot_tell_seat_1s_hands_apart_before_the_reveal(ld_server, monkeypatch) -> None:
    import arena.match.local_match as local_match

    server, _ = ld_server
    seeds = list(_seeds_differing_only_in_seat_1())
    monkeypatch.setattr(local_match, "_mint_seed", lambda: seeds.pop(0))
    moves0 = [{"type": "bid", "quantity": 1, "face": 1}, {"type": "bid", "quantity": 1, "face": 3}]
    moves1 = [{"type": "bid", "quantity": 1, "face": 2}, {"type": "call"}]
    first = asyncio.run(asyncio.wait_for(_play(server, moves0, moves1), timeout=60))
    second = asyncio.run(asyncio.wait_for(_play(server, moves0, moves1), timeout=60))

    for name in ("seat_0", "spectator"):
        a = _prefix_until_reveal(first["frames"][name])
        b = _prefix_until_reveal(second["frames"][name])
        assert len(a) > 5 and a == b, name
    assert _prefix_until_reveal(first["frames"]["seat_1"]) != _prefix_until_reveal(
        second["frames"]["seat_1"]
    )


def test_a_mid_round_reconnect_replays_nothing_hidden(ld_server) -> None:
    server, _ = ld_server

    async def run() -> tuple[list[dict], dict]:
        match = _create(server)
        ws0 = await connect(match["seat_0_url"])
        ws1 = await connect(match["seat_1_url"])
        before: list[dict] = []
        await ws0.send(dumps(_hello(0)))
        token = (await _until(ws0, "welcome", before))["payload"]["resume_token"]
        await ws1.send(dumps(_hello(1)))
        await _until(ws1, "welcome", [])

        await _until(ws0, "observation_request", before)
        await ws0.send(dumps(_bid(0, 1, 2)))
        await _until(ws1, "observation_request", [])
        await ws1.send(dumps(_bid(1, 1, 4)))
        await _until(ws0, "observation_request", before)
        await ws0.close()

        ws0 = await connect(match["seat_0_url"])
        await ws0.send(dumps(_hello(0, token)))
        rewelcome = await _until(ws0, "welcome", [])
        await ws0.close()
        await ws1.close()
        return before, rewelcome

    before, rewelcome = asyncio.run(asyncio.wait_for(run(), timeout=60))
    transcript = rewelcome["payload"]["transcript"]
    assert transcript["view"] == "seat" and transcript["viewer_seat"] == 0
    assert leaked_hand_paths(rewelcome, 0) == []
    live = [f["payload"]["turn_record"] for f in before if f["type"] == "turn_committed"]
    replayed = transcript["match_transcript"]["turns"]
    assert len(replayed) == len(live)
    for record, turn in zip(live, replayed):
        for key in ("kind", "seat", "action", "outcome", "events", "post_snapshot"):
            assert record[key] == turn[key], key


def _bid(seat: int, quantity: int, face: int) -> Any:
    import uuid

    from arena.adapters.in_process import ActionResponsePayload
    from arena.adapters.websocket.envelope import ActionResponseEnvelope
    from arena.adapters.websocket.messages import ActionResponseBody

    return ActionResponseEnvelope(
        schema_version=3,
        seat=seat,
        turn_id=str(uuid.uuid4()),
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id="liarsdice",
                schema_version=1,
                seat=seat,
                action={"type": "bid", "quantity": quantity, "face": face},
            )
        ),
    )
