"""GET /matches/{id}/public-transcript over real TCP (Phase 40 Slices 2-3).

* The stored transcript is exactly what a spectator received in the terminal
  frame, and it outlives the connections and the registry.
* A Liar's Dice public transcript carries no hand but the revealed ones.
* An aborted match's transcript is served too.
* A failing store does not stop a match from ending properly.
* With a durable store (file, SQLite) the transcript survives a restart.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from arena.games.liarsdice.audit import leaked_hand_paths
from arena.runtime.payloads import dump_runtime_transcript
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from arena.server.transcript_store import (
    FileTranscriptStore,
    MemoryTranscriptStore,
    SqliteTranscriptStore,
)
from tests.integration._ws_client import connect, play_scripted, send_envelope
from tests.integration.conftest import serve
from tests.integration.test_hidden_information import _hello
from tests.integration.test_liarsdice_wire import _drain, _play
from tests.integration.test_spectator import _spectator_hello


def _transcript_of(frames: list[str], frame_type: str) -> dict[str, Any]:
    for raw in frames:
        frame = json.loads(raw)
        if frame["type"] == frame_type:
            return frame["payload"]["transcript"]
    raise AssertionError(f"no {frame_type} frame")


def _get(base: str, match_id: str) -> httpx.Response:
    return httpx.get(f"{base}/matches/{match_id}/public-transcript")


def _first_legal(request: Any) -> dict[str, Any]:
    return request.observation["legal_actions"][0]


async def _play_tictactoe(base: str, ws_base: str, **extra: Any) -> dict[str, Any]:
    match = httpx.post(f"{base}/matches", json={"game_id": "tictactoe", **extra}).json()
    frames: dict[str, list[str]] = {"seat_0": [], "seat_1": []}
    spectate = f"{ws_base}/matches/{match['match_id']}/spectate"
    async with (
        await connect(match["seat_0_url"]) as ws0,
        await connect(match["seat_1_url"]) as ws1,
        await connect(spectate) as spec,
    ):
        await send_envelope(spec, _spectator_hello())
        welcome = await spec.recv()
        spectator = asyncio.create_task(_drain(spec))
        await asyncio.gather(
            play_scripted(ws0, 0, _first_legal, frames=frames["seat_0"]),
            play_scripted(ws1, 1, _first_legal, frames=frames["seat_1"]),
        )
        frames["spectator"] = [welcome, *await asyncio.wait_for(spectator, timeout=10)]
    return {"match_id": match["match_id"], "frames": frames}


def test_a_finished_match_is_served_exactly_as_the_spectator_saw_it() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as server:
        played = asyncio.run(_play_tictactoe(server.http_base_url, server.ws_base_url))
        resp = _get(server.http_base_url, played["match_id"])
        # The registry forgetting the match does not matter: the store has it.
        app.state.match_registry.delete(played["match_id"])
        after_eviction = _get(server.http_base_url, played["match_id"])

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "no-store" in resp.headers["cache-control"]
    body = resp.json()
    assert body == _transcript_of(played["frames"]["spectator"], "match_finished")
    assert body["lifecycle"] == "finished"
    assert after_eviction.status_code == 200 and after_eviction.json() == body


def test_a_liars_dice_public_transcript_leaks_no_hand() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as server:
        played = asyncio.run(_play(server, [], []))
        match_id = played["match_id"]
        body = _get(server.http_base_url, match_id).json()
        full = dump_runtime_transcript(app.state.match_registry.get(match_id).session)

    assert body == _transcript_of(played["frames"]["spectator"], "match_finished")
    assert body["view"] == "public"
    assert leaked_hand_paths(body, None) == []
    text = json.dumps(body)
    assert "DiceDealt" not in text
    # Ground truth: the full transcript has hands the public one does not.
    assert "DiceDealt" in json.dumps(full)
    assert body["match_transcript"]["turns"], "the public transcript still has every turn"
    assert len(body["match_transcript"]["turns"]) == len(full["match_transcript"]["turns"])


def test_an_aborted_match_is_served() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(base: str, ws_base: str) -> dict[str, Any]:
        match = httpx.post(
            f"{base}/matches",
            json={"game_id": "tictactoe", "per_turn_deadline_ms": 300, "disconnect_grace_ms": 300},
        ).json()
        # Both seats join and then never answer: the turn deadline aborts.
        async with await connect(match["seat_0_url"]) as ws0, await connect(
            match["seat_1_url"]
        ) as ws1:
            await send_envelope(ws0, _hello(0))
            await send_envelope(ws1, _hello(1))
            frames = await asyncio.wait_for(_drain(ws1), timeout=15)
        return {"match_id": match["match_id"], "frames": frames}

    with serve(app) as server:
        played = asyncio.run(run(server.http_base_url, server.ws_base_url))
        resp = _get(server.http_base_url, played["match_id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["lifecycle"] == "aborted"
    assert body["abort"]["reason"] == "turn_deadline_expired"
    assert body == _transcript_of(played["frames"], "match_aborted")


class _BrokenStore(MemoryTranscriptStore):
    def put(self, match_id: str, body: bytes, *, audience: str) -> Any:
        raise OSError("disk full")


def test_a_failing_store_does_not_stop_the_match_from_ending() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited(), transcript_store=_BrokenStore())
    with serve(app) as server:
        played = asyncio.run(_play_tictactoe(server.http_base_url, server.ws_base_url))
        resp = _get(server.http_base_url, played["match_id"])
    for seat in ("seat_0", "seat_1"):
        assert _transcript_of(played["frames"][seat], "match_finished")["lifecycle"] == "finished"
    assert resp.status_code == 404


@pytest.mark.parametrize("backend", ["file", "sqlite"])
def test_a_durable_store_serves_the_transcript_after_a_restart(
    backend: str, tmp_path: Path
) -> None:
    def open_store() -> Any:
        if backend == "file":
            return FileTranscriptStore(tmp_path / "transcripts")
        return SqliteTranscriptStore(tmp_path / "arena.sqlite3")

    first = create_app(rate_limiter=RateLimiter.unlimited(), transcript_store=open_store())
    with serve(first) as server:
        played = asyncio.run(_play(server, [], []))
        before = _get(server.http_base_url, played["match_id"]).json()

    # A new process: nothing in memory, the same store on disk.
    second = create_app(rate_limiter=RateLimiter.unlimited(), transcript_store=open_store())
    with serve(second) as server:
        assert second.state.match_registry.list_match_ids() == ()
        after = _get(server.http_base_url, played["match_id"])

    assert after.status_code == 200
    assert after.json() == before
    assert leaked_hand_paths(after.json(), None) == []
