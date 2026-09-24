"""Spectator channel over real WebSockets (Phase 36 Slice 3).

`WS /matches/{id}/spectate` was reserved in v1 and closed `4404`. It now serves a
read-only view of a match.

This phase deliberately ships **no new or changed wire fields**: spectators get
two new message types (`spectator_hello` / `spectator_welcome`, which §7 permits
without a schema bump) and receive the existing `post_snapshot`, which for a
perfect-information game already *is* the public view. Per-seat redaction and
`public_snapshot` arrive with Phase 38's bump.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
import websockets

from arena.adapters.in_process import ActionResponsePayload
from arena.adapters.websocket import WIRE_SCHEMA_VERSION
from arena.adapters.websocket.envelope import ActionResponseEnvelope, SpectatorHelloEnvelope
from arena.adapters.websocket.messages import ActionResponseBody, SpectatorHelloBody
from tests.integration._ws_client import connect, play_scripted, recv_envelope, send_envelope
from tests.integration.conftest import RunningServer


def _first_legal_connect4(obs_payload: Any) -> dict[str, Any]:
    legal = obs_payload.observation["legal_actions"]
    return {"column": legal[0]["column"]}


def _spectator_hello() -> SpectatorHelloEnvelope:
    return SpectatorHelloEnvelope(
        schema_version=1,
        payload=SpectatorHelloBody(
            client_name="test-spectator",
            client_version="0.1.0",
            supported_schema_versions=[1, 2, 3, 4],
        ),
    )


def _action_response() -> ActionResponseEnvelope:
    """A structurally valid action, so it is refused for who sent it."""

    return ActionResponseEnvelope(
        schema_version=1,
        seat=0,
        turn_id=str(uuid.uuid4()),
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id='connect4',
                schema_version=1,
                seat=0,
                action={'column': 0},
            )
        ),
    )


def _create_match(http_base: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "game_id": "connect4",
        "players": [{"label": "alice"}, {"label": "bob"}],
        **extra,
    }
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _spectate_url(running_server: RunningServer, match_id: str) -> str:
    return f"{running_server.ws_base_url}/matches/{match_id}/spectate"


async def _drain_spectator(ws: Any) -> list[Any]:
    """Collect every envelope a spectator receives until its socket closes."""

    seen: list[Any] = []
    try:
        while True:
            seen.append(await recv_envelope(ws))
    except websockets.exceptions.ConnectionClosed:
        pass
    return seen


def test_spectator_sees_a_whole_match_and_never_gets_seat_only_messages(
    running_server: RunningServer,
) -> None:
    """The core acceptance criterion for Slice 3.

    A third client attaches to a running match, receives every committed turn
    live, and never receives `observation_request` or `action_rejected` — those
    are addressed to a seat, and a spectator holds none.
    """

    async def run() -> None:
        match = _create_match(running_server.http_base_url)

        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
            await connect(_spectate_url(running_server, match["match_id"])) as spec,
        ):
            await send_envelope(spec, _spectator_hello())
            welcome = await recv_envelope(spec)
            assert welcome.type == "spectator_welcome"
            assert welcome.payload.lifecycle == "created"

            spectate_task = asyncio.create_task(_drain_spectator(spec))

            (_, transcript_0), _ = await asyncio.gather(
                play_scripted(ws0, 0, _first_legal_connect4),
                play_scripted(ws1, 1, _first_legal_connect4),
            )
            seen = await asyncio.wait_for(spectate_task, timeout=10)

        assert transcript_0 is not None
        assert transcript_0.lifecycle == "finished"

        types = [env.type for env in seen]
        assert "observation_request" not in types
        assert "action_rejected" not in types

        # Every committed turn reached the spectator.
        committed = [env for env in seen if env.type == "turn_committed"]
        assert len(committed) == len(transcript_0.match_transcript["turns"])
        assert types[-1] == "match_finished"

        # For a perfect-information game the spectator's snapshot is the seats'.
        assert committed[0].payload.post_snapshot is not None

        # Phase 37: events are load-bearing on the wire, not class-name strings.
        # A chance outcome cannot be recomputed by a client, so it has to arrive
        # here; this asserts the channel that will carry it.
        first_events = committed[0].payload.events
        assert first_events, "turn_committed must carry its domain events"
        assert first_events[0]["event_type"] == "DiscDropped"
        assert first_events[0]["payload"]["seat"] == 0
        assert committed[0].payload.turn_record["kind"] == "action"

    asyncio.run(asyncio.wait_for(run(), timeout=60))


def test_seats_are_unaffected_by_spectator_count(running_server: RunningServer) -> None:
    """Zero, one, and several spectators all produce the same match outcome."""

    async def play_with(spectator_count: int) -> str:
        match = _create_match(running_server.http_base_url)
        spectators = [
            await connect(_spectate_url(running_server, match["match_id"]))
            for _ in range(spectator_count)
        ]
        try:
            for spec in spectators:
                await send_envelope(spec, _spectator_hello())
                assert (await recv_envelope(spec)).type == "spectator_welcome"
            drains = [asyncio.create_task(_drain_spectator(s)) for s in spectators]

            async with (
                await connect(match["seat_0_url"]) as ws0,
                await connect(match["seat_1_url"]) as ws1,
            ):
                (_, transcript_0), _ = await asyncio.gather(
                    play_scripted(ws0, 0, _first_legal_connect4),
                    play_scripted(ws1, 1, _first_legal_connect4),
                )
            for drain in drains:
                await asyncio.wait_for(drain, timeout=10)
            assert transcript_0 is not None
            return transcript_0.lifecycle
        finally:
            for spec in spectators:
                await spec.close()

    async def run() -> None:
        assert await play_with(0) == "finished"
        assert await play_with(1) == "finished"
        assert await play_with(3) == "finished"

    asyncio.run(asyncio.wait_for(run(), timeout=90))


def test_spectator_attaching_to_a_finished_match_gets_the_transcript(
    running_server: RunningServer,
) -> None:
    """Late arrivals still get the whole history, then a clean close."""

    async def run() -> None:
        match = _create_match(running_server.http_base_url)

        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            await asyncio.gather(
                play_scripted(ws0, 0, _first_legal_connect4),
                play_scripted(ws1, 1, _first_legal_connect4),
            )

        async with await connect(_spectate_url(running_server, match["match_id"])) as spec:
            await send_envelope(spec, _spectator_hello())
            welcome = await recv_envelope(spec)

            assert welcome.type == "spectator_welcome"
            assert welcome.payload.lifecycle == "finished"
            assert welcome.payload.turn_count > 0
            assert welcome.payload.transcript is not None

            # Nothing further is coming; the server closes.
            with pytest.raises(websockets.exceptions.ConnectionClosed):
                await recv_envelope(spec)

    asyncio.run(asyncio.wait_for(run(), timeout=60))


def test_spectator_may_not_act(running_server: RunningServer) -> None:
    """An action from a spectator is refused; the match is unaffected."""

    async def run() -> None:
        match = _create_match(running_server.http_base_url)

        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
            await connect(_spectate_url(running_server, match["match_id"])) as spec,
        ):
            await send_envelope(spec, _spectator_hello())
            assert (await recv_envelope(spec)).type == "spectator_welcome"

            # A well-formed action from a seatless client: decodable, and
            # refused on authority rather than on shape.
            await send_envelope(spec, _action_response())

            saw_error = False
            try:
                while True:
                    env = await asyncio.wait_for(recv_envelope(spec), timeout=5)
                    if env.type == "error":
                        saw_error = True
                        assert env.payload.code == "protocol_violation"
            except (websockets.exceptions.ConnectionClosed, TimeoutError, asyncio.TimeoutError):
                pass

            assert saw_error

            # The match still completes normally.
            (_, transcript_0), _ = await asyncio.gather(
                play_scripted(ws0, 0, _first_legal_connect4),
                play_scripted(ws1, 1, _first_legal_connect4),
            )
            assert transcript_0 is not None
            assert transcript_0.lifecycle == "finished"

    asyncio.run(asyncio.wait_for(run(), timeout=60))


def test_spectator_negotiates_the_wire_version(running_server: RunningServer) -> None:
    """A spectator that cannot speak the server's schema is refused."""

    async def run() -> None:
        match = _create_match(running_server.http_base_url)

        async with await connect(_spectate_url(running_server, match["match_id"])) as spec:
            bad = SpectatorHelloEnvelope(
                schema_version=WIRE_SCHEMA_VERSION,
                payload=SpectatorHelloBody(
                    client_name="from-the-future",
                    client_version="9.9.9",
                    supported_schema_versions=[99],
                ),
            )
            await send_envelope(spec, bad)
            with pytest.raises(websockets.exceptions.ConnectionClosed) as exc:
                await recv_envelope(spec)
            assert exc.value.rcvd is not None
            assert exc.value.rcvd.code == 4400

    asyncio.run(asyncio.wait_for(run(), timeout=30))
