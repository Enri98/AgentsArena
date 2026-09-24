"""Rock-Paper-Scissors over real TCP: the Phase 41 acceptance criteria.

* Both seats get their observation request at once, before either acts.
* A seat that has thrown learns nothing about the other's throw until the round
  commits, and the round commits as one joint turn, to seats and spectators.
* The match finishes end to end; its transcripts validate and replay.
* A seat that misses its deadline aborts the match through the existing path.
* A rejected throw costs only that seat a retry.
* The SDK plays it unchanged.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import websockets

from arena.adapters.in_process import ActionResponsePayload
from arena.adapters.websocket import dumps
from arena.adapters.websocket.envelope import ActionResponseEnvelope
from arena.adapters.websocket.messages import ActionResponseBody
from arena.games import build_default_registry
from arena.runtime.payloads import dump_runtime_transcript, validate_runtime_transcript
from arena.sdk import connect as sdk_connect
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration._ws_client import connect, play_scripted, send_envelope
from tests.integration.conftest import serve
from tests.integration.test_hidden_information import _hello
from tests.integration.test_liarsdice_wire import _drain
from tests.integration.test_spectator import _spectator_hello

RPS = build_default_registry().get("rps")


def _create(base: str, **extra: Any) -> dict:
    resp = httpx.post(f"{base}/matches", json={"game_id": "rps", **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _throw(shape: str):  # type: ignore[no-untyped-def]
    return lambda request: {"shape": shape}


def _action(match_id: str, seat: int, shape: str) -> Any:
    return ActionResponseEnvelope(
        schema_version=4,
        match_id=match_id,
        seat=seat,
        turn_id=str(uuid.uuid4()),
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id="rps", schema_version=1, seat=seat, action={"shape": shape}
            )
        ),
    )


async def _next(ws: Any, frame_type: str, timeout: float = 5.0) -> dict:
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if frame["type"] == frame_type:
            return frame


def test_a_match_plays_to_the_end_with_joint_turns() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(base: str, ws_base: str) -> dict:
        match = _create(base, game_config={"target_wins": 2, "max_rounds": 10})
        frames: dict[str, list[str]] = {"seat_0": [], "seat_1": []}
        spectate = f"{ws_base}/matches/{match['match_id']}/spectate"
        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
            await connect(spectate) as spec,
        ):
            await send_envelope(spec, _spectator_hello())
            await spec.recv()
            spectator = asyncio.create_task(_drain(spec))
            results = await asyncio.gather(
                play_scripted(ws0, 0, _throw("rock"), frames=frames["seat_0"]),
                play_scripted(ws1, 1, _throw("scissors"), frames=frames["seat_1"]),
            )
            frames["spectator"] = await asyncio.wait_for(spectator, timeout=10)
        return {"match_id": match["match_id"], "frames": frames, "results": results}

    with serve(app) as server:
        out = asyncio.run(asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 60))
        full = dump_runtime_transcript(app.state.match_registry.get(out["match_id"]).session)

    transcript = out["results"][0][1]
    assert transcript.lifecycle == "finished"
    turns = transcript.match_transcript["turns"]
    assert [t["kind"] for t in turns] == ["joint", "joint"]
    assert turns[0]["actions"] == {"0": {"shape": "rock"}, "1": {"shape": "scissors"}}
    validate_runtime_transcript(RPS, json.loads(json.dumps(full)))
    for who in ("seat_0", "seat_1", "spectator"):
        committed = [
            json.loads(f) for f in out["frames"][who] if '"turn_committed"' in f
        ]
        assert [c["payload"]["turn_record"]["kind"] for c in committed] == ["joint", "joint"]
        states = [json.loads(f) for f in out["frames"][who] if '"match_state"' in f]
        assert any(s["payload"].get("acting_seats") == [0, 1] for s in states), who


def test_both_seats_are_asked_at_once_and_no_throw_leaks_before_the_round() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(base: str, ws_base: str) -> dict:
        match = _create(base, game_config={"target_wins": 1}, per_turn_deadline_ms=10_000)
        mid = match["match_id"]
        async with await connect(match["seat_0_url"]) as ws0, await connect(
            match["seat_1_url"]
        ) as ws1:
            await send_envelope(ws0, _hello(0))
            await send_envelope(ws1, _hello(1))
            obs0 = await _next(ws0, "observation_request")
            obs1 = await _next(ws1, "observation_request")  # before seat 0 has acted
            await send_envelope(ws0, _action(mid, 0, "paper"))
            # Seat 1 waits: nothing about seat 0's throw may reach it meanwhile.
            seen_meanwhile: list[str] = []
            try:
                while True:
                    seen_meanwhile.append(await asyncio.wait_for(ws1.recv(), 0.7))
            except asyncio.TimeoutError:
                pass
            await send_envelope(ws1, _action(mid, 1, "rock"))
            committed = await _next(ws1, "turn_committed")
            finished = await _next(ws1, "match_finished")
        return {
            "obs": (obs0["seat"], obs1["seat"]),
            "meanwhile": seen_meanwhile,
            "committed": committed,
            "finished": finished,
        }

    with serve(app) as server:
        out = asyncio.run(asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 60))

    assert out["obs"] == (0, 1)
    assert not any("paper" in frame for frame in out["meanwhile"]), out["meanwhile"]
    assert out["committed"]["payload"]["turn_record"]["actions"] == {
        "0": {"shape": "paper"},
        "1": {"shape": "rock"},
    }
    assert out["finished"]["payload"]["transcript"]["lifecycle"] == "finished"


def test_a_seat_that_never_throws_aborts_on_its_deadline() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(base: str, ws_base: str) -> dict:
        match = _create(base, per_turn_deadline_ms=600, disconnect_grace_ms=500)
        mid = match["match_id"]
        async with await connect(match["seat_0_url"]) as ws0, await connect(
            match["seat_1_url"]
        ) as ws1:
            await send_envelope(ws0, _hello(0))
            await send_envelope(ws1, _hello(1))
            await _next(ws0, "observation_request")
            await _next(ws1, "observation_request")
            await send_envelope(ws0, _action(mid, 0, "rock"))  # seat 1 stays silent
            aborted = await _next(ws0, "match_aborted", timeout=10)
        return aborted

    with serve(app) as server:
        aborted = asyncio.run(asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 60))
    assert aborted["payload"]["abort"]["reason"] == "turn_deadline_expired"
    transcript = aborted["payload"]["transcript"]
    assert transcript["lifecycle"] == "aborted"
    # The throw seat 0 made in the unfinished round is nowhere in the result.
    assert transcript["match_transcript"]["turns"] == []
    assert "rock" not in json.dumps(transcript)


def test_a_rejected_throw_costs_only_that_seat_a_retry() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(base: str, ws_base: str) -> dict:
        match = _create(base, game_config={"target_wins": 1}, per_action_retry_budget=1)
        mid = match["match_id"]
        async with await connect(match["seat_0_url"]) as ws0, await connect(
            match["seat_1_url"]
        ) as ws1:
            await send_envelope(ws0, _hello(0))
            await send_envelope(ws1, _hello(1))
            await _next(ws0, "observation_request")
            await _next(ws1, "observation_request")
            await ws1.send(
                dumps(_action(mid, 1, "rock")).replace('"rock"', '"lizard"')
            )
            rejected = await _next(ws1, "action_rejected")
            await send_envelope(ws0, _action(mid, 0, "scissors"))
            await send_envelope(ws1, _action(mid, 1, "rock"))
            finished = await _next(ws0, "match_finished")
            try:
                extra = await asyncio.wait_for(ws0.recv(), 0.3)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                extra = None
        return {"rejected": rejected, "finished": finished, "extra": extra}

    with serve(app) as server:
        out = asyncio.run(asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 60))
    assert out["rejected"]["seat"] == 1
    assert out["rejected"]["payload"]["retries_remaining"] == 1
    result_turn = out["finished"]["payload"]["transcript"]["match_transcript"]["turns"][0]
    assert result_turn["actions"]["1"] == {"shape": "rock"}


def test_the_sdk_plays_a_simultaneous_game_unchanged() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(base: str) -> Any:
        match = _create(base)
        return await asyncio.gather(
            sdk_connect(match["seat_0_url"], 0, lambda r: {"shape": "paper"}),
            sdk_connect(match["seat_1_url"], 1, lambda r: {"shape": "rock"}),
        )

    with serve(app) as server:
        results = asyncio.run(asyncio.wait_for(run(server.http_base_url), 60))
    for _result, transcript in results:
        assert transcript.lifecycle == "finished"
        assert len(transcript.match_transcript["turns"]) == 3  # paper beats rock, 3 wins


def test_a_seat_that_drops_mid_round_resumes_it() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(base: str, ws_base: str) -> dict:
        match = _create(
            base,
            game_config={"target_wins": 1},
            per_turn_deadline_ms=10_000,
            disconnect_grace_ms=5_000,
        )
        mid = match["match_id"]
        async with await connect(match["seat_0_url"]) as ws0:
            ws1 = await connect(match["seat_1_url"])
            await send_envelope(ws0, _hello(0))
            await send_envelope(ws1, _hello(1))
            token = (await _next(ws1, "welcome"))["payload"]["resume_token"]
            await _next(ws0, "observation_request")
            await _next(ws1, "observation_request")
            await send_envelope(ws0, _action(mid, 0, "scissors"))  # seat 0 has thrown
            await ws1.close()  # seat 1 drops before throwing
            await asyncio.sleep(0.3)
            async with await connect(match["seat_1_url"]) as ws1b:
                await send_envelope(ws1b, _hello(1, token))
                welcome = await _next(ws1b, "welcome")
                resent = await _next(ws1b, "observation_request")
                await send_envelope(ws1b, _action(mid, 1, "paper"))
                finished = await _next(ws1b, "match_finished")
            done0 = await _next(ws0, "match_finished")
        return {"welcome": welcome, "resent": resent, "finished": finished, "done0": done0}

    with serve(app) as server:
        out = asyncio.run(asyncio.wait_for(run(server.http_base_url, server.ws_base_url), 60))
    # The resumed seat sees nothing of seat 0's pending throw, even in its replay.
    assert "scissors" not in json.dumps(out["welcome"])
    assert out["resent"]["seat"] == 1
    assert 0 < out["resent"]["payload"]["deadline_ms"] < 10_000
    turn = out["done0"]["payload"]["transcript"]["match_transcript"]["turns"][0]
    assert turn["actions"] == {"0": {"shape": "scissors"}, "1": {"shape": "paper"}}
