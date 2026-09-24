"""Hidden information over the wire (Phase 38 acceptance).

The secrets game deals each seat a private digit at an opening chance node. The
strongest statement of "seat 0 learns nothing about seat 1's digit" is
**indistinguishability**: play two matches in which seat 0 is dealt the same
digit and seat 1 a different one. Every frame seat 0 receives — welcome config,
every turn_committed (snapshots, events, chance outcomes), observation requests,
match_state, and the final transcript — must be identical across the two, once
per-match identifiers are set aside. The same must hold for a spectator, whose
view may depend on neither digit.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import websockets

from arena.core.chance import ChanceRng
from arena.runtime.payloads import validate_runtime_transcript
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from arena.testing.hidden_factory import DIGITS, build_secrets_game_definition
from tests.integration._ws_client import connect, play_scripted, send_envelope
from tests.integration.conftest import RunningServer, serve
from tests.integration.test_spectator import _spectator_hello

#: Identifiers that differ between any two matches by construction.
_PER_MATCH_KEYS = {"match_id", "resume_token", "turn_id", "nonce"}


def _deal(seed: int) -> tuple[int, ...]:
    return ChanceRng(seed=seed).draw_many(DIGITS, 2)[0]


def _seeds_with_same_seat0_digit() -> tuple[int, int]:
    """Two seeds dealing seat 0 the same digit and seat 1 different ones."""

    first = _deal(1)
    for seed in range(2, 10_000):
        deal = _deal(seed)
        if deal[0] == first[0] and deal[1] != first[1]:
            return 1, seed
    raise AssertionError("no suitable seed pair")  # pragma: no cover


def _normalise(frames: list[str]) -> list[Any]:
    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in _PER_MATCH_KEYS}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    return [strip(json.loads(frame)) for frame in frames]


@pytest.fixture(scope="module")
def secrets_server() -> Iterator[tuple[RunningServer, Any]]:
    from arena.games import build_default_registry

    registry = build_default_registry()
    registry.register(build_secrets_game_definition())
    app = create_app(registry, rate_limiter=RateLimiter.unlimited())
    with serve(app) as running:
        yield running, app


async def _drain_spectator(ws: Any) -> list[str]:
    frames: list[str] = []
    try:
        while True:
            raw = await ws.recv()
            frames.append(raw if isinstance(raw, str) else raw.decode())
    except websockets.exceptions.ConnectionClosed:
        pass
    return frames


def _pass(_: Any) -> dict[str, Any]:
    return {"type": "pass"}


async def _play(server: RunningServer) -> dict[str, Any]:
    resp = httpx.post(
        f"{server.http_base_url}/matches",
        json={
            "game_id": "secrets-game",
            "players": [{"label": "a"}, {"label": "b"}],
            "game_config": {"max_turns": 4},
            "supported_schema_versions": [3],
        },
    )
    assert resp.status_code == 201, resp.text
    match = resp.json()
    frames: dict[str, list[str]] = {"seat_0": [], "seat_1": []}
    spectate_url = f"{server.ws_base_url}/matches/{match['match_id']}/spectate"

    async with (
        await connect(match["seat_0_url"]) as ws0,
        await connect(match["seat_1_url"]) as ws1,
        await connect(spectate_url) as spec,
    ):
        await send_envelope(spec, _spectator_hello())
        # Finish the handshake before play starts, so both runs attach at the
        # same point and their spectator streams are comparable.
        welcome = await spec.recv()
        spectator = asyncio.create_task(_drain_spectator(spec))
        (_, transcript_0), (_, transcript_1) = await asyncio.gather(
            play_scripted(ws0, 0, _pass, frames=frames["seat_0"]),
            play_scripted(ws1, 1, _pass, frames=frames["seat_1"]),
        )
        frames["spectator"] = [welcome, *await asyncio.wait_for(spectator, timeout=10)]

    return {
        "match_id": match["match_id"],
        "frames": frames,
        "transcript_0": transcript_0,
        "transcript_1": transcript_1,
    }


def _run_pair(secrets_server, monkeypatch) -> tuple[dict, dict, tuple[int, int]]:
    import arena.match.local_match as local_match

    server, _ = secrets_server
    seeds = _seeds_with_same_seat0_digit()
    queue = list(seeds)
    monkeypatch.setattr(local_match, "_mint_seed", lambda: queue.pop(0))
    first = asyncio.run(asyncio.wait_for(_play(server), timeout=60))
    second = asyncio.run(asyncio.wait_for(_play(server), timeout=60))
    return first, second, seeds


def test_seat_0_cannot_tell_two_matches_apart_by_seat_1s_digit(
    secrets_server, monkeypatch
) -> None:
    first, second, seeds = _run_pair(secrets_server, monkeypatch)
    assert _deal(seeds[0])[1] != _deal(seeds[1])[1]

    assert _normalise(first["frames"]["seat_0"]) == _normalise(second["frames"]["seat_0"])
    assert _normalise(first["frames"]["spectator"]) == _normalise(second["frames"]["spectator"])
    # Sanity: the test can see a difference where one is allowed.
    assert _normalise(first["frames"]["seat_1"]) != _normalise(second["frames"]["seat_1"])


def test_every_frame_is_the_recipients_own_view(secrets_server, monkeypatch) -> None:
    first, _, seeds = _run_pair(secrets_server, monkeypatch)
    deal = _deal(seeds[0])

    for name in ("seat_0", "seat_1", "spectator"):
        for frame in first["frames"][name]:
            assert '"secrets"' not in frame, f"the full deal reached {name}"

    seat_0 = [json.loads(f) for f in first["frames"]["seat_0"]]
    committed = [f["payload"] for f in seat_0 if f["type"] == "turn_committed"]
    opening = committed[0]
    assert opening["turn_record"]["kind"] == "chance"
    assert opening["turn_record"]["outcome"] == {"my_secret": deal[0]}
    assert [e["event_type"] for e in opening["events"]] == ["SecretsDealt", "SecretReceived"]
    assert opening["events"][1]["payload"] == {"seat": 0, "secret": deal[0]}
    assert opening["post_snapshot"]["state"]["my_secret"] == deal[0]
    assert "my_secret" not in opening["public_snapshot"]["state"]

    spectator = [json.loads(f) for f in first["frames"]["spectator"]]
    spec_opening = next(f["payload"] for f in spectator if f["type"] == "turn_committed")
    assert spec_opening["turn_record"]["outcome"] == {}
    assert [e["event_type"] for e in spec_opening["events"]] == ["SecretsDealt"]
    assert spec_opening["post_snapshot"] == spec_opening["public_snapshot"]

    transcript_0 = first["transcript_0"]
    assert transcript_0.view == "seat" and transcript_0.viewer_seat == 0
    assert transcript_0.match_transcript["view"] == "seat"
    finished = next(f for f in spectator if f["type"] == "match_finished")
    assert finished["payload"]["transcript"]["view"] == "public"


def test_the_servers_full_transcript_still_validates(secrets_server, monkeypatch) -> None:
    from arena.runtime.payloads import dump_runtime_transcript

    _, app = secrets_server
    first, _, _ = _run_pair(secrets_server, monkeypatch)
    match = app.state.match_registry.get(first["match_id"])
    full = dump_runtime_transcript(match.session)
    assert full["view"] == "full"
    validate_runtime_transcript(build_secrets_game_definition(), full)

    # A seat's transcript cannot be replayed: it lacks the other hand.
    with pytest.raises(ValueError, match="cannot be loaded or replayed"):
        validate_runtime_transcript(
            build_secrets_game_definition(), first["transcript_0"].model_dump(mode="json")
        )


def test_a_client_without_v3_is_refused_for_every_game(secrets_server) -> None:
    server, _ = secrets_server
    resp = httpx.post(
        f"{server.http_base_url}/matches",
        json={"game_id": "secrets-game", "supported_schema_versions": [1, 2]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "schema_version_unsupported"


# ---------------------------------------------------------------------------
# Reconnect replay (protocol §11): the seat's own history, nothing more
# ---------------------------------------------------------------------------


def _hello(seat: int, resume_token: str | None = None) -> Any:
    from arena.adapters.websocket.envelope import HelloEnvelope
    from arena.adapters.websocket.messages import HelloBody

    return HelloEnvelope(
        schema_version=3,
        seat=seat,
        payload=HelloBody(
            client_name="test",
            client_version="0.1.0",
            supported_schema_versions=[3],
            requested_seat=seat,
            resume_token=resume_token,
        ),
    )


def _pass_env(seat: int) -> Any:
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
                game_id="secrets-game", schema_version=1, seat=seat, action={"type": "pass"}
            )
        ),
    )


async def _until(ws: Any, wanted: str, seen: list[dict]) -> dict:
    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        seen.append(frame)
        if frame["type"] == wanted:
            return frame


def test_a_reconnect_replays_the_seats_own_history_and_adds_nothing(secrets_server) -> None:
    from arena.adapters.websocket import dumps

    server, _ = secrets_server

    async def run() -> tuple[list[dict], dict]:
        resp = httpx.post(
            f"{server.http_base_url}/matches",
            json={
                "game_id": "secrets-game",
                "game_config": {"max_turns": 4},
                "disconnect_grace_ms": 10_000,
            },
        )
        match = resp.json()
        before: list[dict] = []
        seat_1_seen: list[dict] = []

        ws0 = await connect(match["seat_0_url"])
        ws1 = await connect(match["seat_1_url"])
        await ws0.send(dumps(_hello(0)))
        welcome = await _until(ws0, "welcome", before)
        await ws1.send(dumps(_hello(1)))
        await _until(ws1, "welcome", seat_1_seen)

        # Seat 0 passes, seat 1 passes; seat 0 is to move again, then drops.
        await _until(ws0, "observation_request", before)
        await ws0.send(dumps(_pass_env(0)))
        await _until(ws1, "observation_request", seat_1_seen)
        await ws1.send(dumps(_pass_env(1)))
        await _until(ws0, "observation_request", before)
        await ws0.close()

        ws0 = await connect(match["seat_0_url"])
        await ws0.send(dumps(_hello(0, welcome["payload"]["resume_token"])))
        after: list[dict] = []
        rewelcome = await _until(ws0, "welcome", after)

        # Finish the match so the server driver exits cleanly.
        await _until(ws0, "observation_request", after)
        await ws0.send(dumps(_pass_env(0)))
        await _until(ws1, "observation_request", seat_1_seen)
        await ws1.send(dumps(_pass_env(1)))
        await _until(ws0, "match_finished", after)
        await ws0.close()
        await ws1.close()
        return before, rewelcome

    before, rewelcome = asyncio.run(asyncio.wait_for(run(), timeout=60))

    transcript = rewelcome["payload"]["transcript"]
    assert transcript is not None, "a reconnect welcome must carry the transcript (§11)"
    assert transcript["view"] == "seat" and transcript["viewer_seat"] == 0
    assert '"secrets"' not in json.dumps(transcript)

    # Exactly the turns seat 0 was sent live, field for field: reconnecting
    # recovered what it missed and learned nothing it was not already told.
    live = [f["payload"]["turn_record"] for f in before if f["type"] == "turn_committed"]
    replayed = transcript["match_transcript"]["turns"]
    assert len(replayed) == len(live) == 3
    for record, turn in zip(live, replayed):
        for key in ("kind", "seat", "action", "outcome", "events", "post_snapshot"):
            assert record[key] == turn[key], key
    assert rewelcome["payload"]["match_config"] == {"max_turns": 4}


# ---------------------------------------------------------------------------
# Adversarial review of Phase 38 Slices 2-3
# ---------------------------------------------------------------------------


def test_no_seat_can_be_claimed_or_resumed_after_the_match(secrets_server) -> None:
    """A finished match releases its seats; claiming one must not hand anyone
    holding the match id (every spectator) that seat's private transcript."""

    from arena.adapters.websocket import dumps

    server, _ = secrets_server

    async def run() -> list[tuple[int | None, str]]:
        resp = httpx.post(
            f"{server.http_base_url}/matches",
            json={"game_id": "secrets-game", "game_config": {"max_turns": 2}},
        )
        match = resp.json()
        tokens: list[str] = []
        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            seen0: list[dict] = []
            await ws0.send(dumps(_hello(0)))
            tokens.append((await _until(ws0, "welcome", seen0))["payload"]["resume_token"])
            await ws1.send(dumps(_hello(1)))
            await _until(ws1, "welcome", [])
            await asyncio.gather(
                play_scripted_after_welcome(ws0, 0), play_scripted_after_welcome(ws1, 1)
            )

        outcomes = []
        for hello in (_hello(0), _hello(1), _hello(0, tokens[0])):
            url = match["seat_0_url"] if hello.seat == 0 else match["seat_1_url"]
            async with await connect(url) as ws:
                await ws.send(dumps(hello))
                try:
                    frame = await asyncio.wait_for(ws.recv(), timeout=5)
                    outcomes.append((None, json.loads(frame)["type"]))
                except websockets.exceptions.ConnectionClosed as exc:
                    outcomes.append((exc.rcvd.code if exc.rcvd else None, exc.rcvd.reason))
        return outcomes

    outcomes = asyncio.run(asyncio.wait_for(run(), timeout=60))
    assert outcomes == [(4410, "match_over")] * 3


async def play_scripted_after_welcome(ws: Any, seat: int) -> None:
    from arena.adapters.websocket import dumps

    while True:
        frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if frame["type"] == "observation_request":
            await ws.send(dumps(_pass_env(seat)))
        if frame["type"] in ("match_finished", "match_aborted"):
            return


def test_an_off_turn_reconnect_is_swapped_in_with_no_gap(secrets_server) -> None:
    """Seat 0 drops while seat 1 is to move and comes straight back. The match
    must continue (it used to abort, blaming seat 0), and the replayed history
    plus the live frames after it must cover every turn exactly once."""

    from arena.adapters.websocket import dumps

    server, _ = secrets_server

    async def run() -> tuple[dict, list[dict], dict]:
        resp = httpx.post(
            f"{server.http_base_url}/matches",
            json={
                "game_id": "secrets-game",
                "game_config": {"max_turns": 4},
                "disconnect_grace_ms": 10_000,
            },
        )
        match = resp.json()
        ws0 = await connect(match["seat_0_url"])
        ws1 = await connect(match["seat_1_url"])
        await ws0.send(dumps(_hello(0)))
        token = (await _until(ws0, "welcome", []))["payload"]["resume_token"]
        await ws1.send(dumps(_hello(1)))
        await _until(ws1, "welcome", [])

        await _until(ws0, "observation_request", [])
        await ws0.send(dumps(_pass_env(0)))
        # Seat 1 is to move; seat 0 drops and reconnects before seat 1 acts.
        await _until(ws1, "observation_request", [])
        await ws0.close()
        ws0 = await connect(match["seat_0_url"])
        await ws0.send(dumps(_hello(0, token)))
        after: list[dict] = []
        rewelcome = await _until(ws0, "welcome", after)

        await ws1.send(dumps(_pass_env(1)))
        await _until(ws0, "observation_request", after)
        await ws0.send(dumps(_pass_env(0)))
        await _until(ws1, "observation_request", [])
        await ws1.send(dumps(_pass_env(1)))
        finished = await _until(ws0, "match_finished", after)
        await ws0.close()
        await ws1.close()
        return rewelcome, after, finished

    rewelcome, after, finished = asyncio.run(asyncio.wait_for(run(), timeout=60))

    replayed = len(rewelcome["payload"]["transcript"]["match_transcript"]["turns"])
    live = [
        f["payload"]["turn_record"]["turn_index"]
        for f in after
        if f["type"] == "turn_committed"
    ]
    total = len(finished["payload"]["transcript"]["match_transcript"]["turns"])
    assert live == list(range(replayed, total))
    assert finished["payload"]["transcript"]["lifecycle"] == "finished"


def test_every_envelope_carries_the_match_id_from_post_matches(secrets_server) -> None:
    server, _ = secrets_server

    async def run() -> tuple[str, set[str]]:
        resp = httpx.post(
            f"{server.http_base_url}/matches", json={"game_id": "secrets-game"}
        )
        match = resp.json()
        frames: list[str] = []
        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            await asyncio.gather(
                play_scripted(ws0, 0, _pass, frames=frames), play_scripted(ws1, 1, _pass)
            )
        ids = {json.loads(f).get("match_id") for f in frames} - {None}
        return match["match_id"], ids

    match_id, ids = asyncio.run(asyncio.wait_for(run(), timeout=60))
    assert ids == {match_id}
