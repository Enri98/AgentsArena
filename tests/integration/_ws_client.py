"""Minimal async WebSocket client helpers for integration tests.

Uses `websockets` (v12+) asyncio client.  All helpers are thin — they exist
to centralise the codec and keep test code readable.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect

from arena.adapters.in_process import ObservationRequestPayload
from arena.adapters.websocket import dumps, loads
from arena.adapters.websocket.envelope import (
    MatchFinishedEnvelope,
    WireEnvelope,
)
from arena.runtime.payloads import RuntimeTranscriptPayload


async def connect(url: str) -> ClientConnection:
    """Open a WebSocket connection to `url` and return the connection object."""
    return await ws_connect(url, ping_interval=None)


async def send_envelope(ws: ClientConnection, envelope: WireEnvelope) -> None:  # type: ignore[valid-type]
    """Serialise and send one envelope."""
    await ws.send(dumps(envelope))


async def recv_envelope(ws: ClientConnection) -> WireEnvelope:  # type: ignore[valid-type]
    """Receive one text frame and decode it as a typed envelope."""
    raw = await ws.recv()
    return loads(raw)


async def play_scripted(
    ws: ClientConnection,
    seat: int,
    choose: Callable[[ObservationRequestPayload], dict[str, Any]],
) -> tuple[dict[str, Any], RuntimeTranscriptPayload]:
    """Drive one seat's side of a match from handshake to match_finished.

    Sends a `hello`, waits for `welcome`, then loops:
    - On `observation_request`: call `choose(payload)` and send `action_response`.
    - On `turn_committed` / `match_state`: drain silently (bookkeeping frames).
    - On `match_finished`: return the transcript payload.
    - On `match_aborted`: raise RuntimeError.

    Returns a tuple of (result_dict, transcript_payload) from the match_finished envelope.

    Parameters
    ----------
    ws:
        Open WebSocket connection already pointed at the correct ?seat= URL.
    seat:
        Integer seat id (0 or 1); placed in the hello and action_response envelopes.
    choose:
        Callable that maps an `ObservationRequestPayload` to a raw action dict.
    """
    from arena.adapters.in_process import ActionResponsePayload
    from arena.adapters.websocket.envelope import (
        ActionResponseEnvelope,
        HelloEnvelope,
    )
    from arena.adapters.websocket.messages import (
        ActionResponseBody,
        HelloBody,
    )

    hello = HelloEnvelope(
        schema_version=1,
        seat=seat,
        payload=HelloBody(
            client_name="integration-test",
            client_version="0.1.0",
            supported_schema_versions=[1],
            auth=None,
            requested_seat=seat,
            resume_token=None,
        ),
    )
    await send_envelope(ws, hello)

    welcome = await recv_envelope(ws)
    assert welcome.type == "welcome", f"Expected welcome, got {welcome.type}"
    game_id: str = welcome.payload.game_id  # type: ignore[union-attr]

    while True:
        env = await recv_envelope(ws)

        if env.type == "match_state":
            continue

        if env.type == "turn_committed":
            continue

        if env.type == "match_finished":
            assert isinstance(env, MatchFinishedEnvelope)
            return env.payload.result, env.payload.transcript

        if env.type == "match_aborted":
            raise RuntimeError(
                f"Match aborted: {env.payload.abort}"  # type: ignore[union-attr]
            )

        if env.type == "observation_request":
            obs_payload: ObservationRequestPayload = (
                env.payload.observation_request  # type: ignore[union-attr]
            )
            raw_action = choose(obs_payload)
            action_resp = ActionResponseEnvelope(
                schema_version=1,
                seat=seat,
                turn_id=str(uuid.uuid4()),
                payload=ActionResponseBody(
                    action_response=ActionResponsePayload(
                        game_id=game_id,
                        schema_version=1,
                        seat=seat,
                        action=raw_action,
                    )
                ),
            )
            await send_envelope(ws, action_resp)
            continue

        if env.type == "ping":
            from arena.adapters.websocket.envelope import PongEnvelope
            from arena.adapters.websocket.messages import PongBody

            pong = PongEnvelope(
                schema_version=1,
                match_id=getattr(env, "match_id", None),
                payload=PongBody(nonce=env.payload.nonce),  # type: ignore[union-attr]
            )
            await send_envelope(ws, pong)
            continue

        if env.type == "error":
            raise RuntimeError(
                f"Server sent error envelope: {env.payload}"  # type: ignore[union-attr]
            )

        raise RuntimeError(f"Unexpected envelope type: {env.type}")
