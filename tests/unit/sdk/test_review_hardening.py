"""SDK hardening from the pre-Phase 40 adversarial review."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

import arena.sdk._session as session_module
from arena.adapters.websocket import WIRE_SCHEMA_VERSION, dumps
from arena.adapters.websocket.envelope import ErrorEnvelope, WelcomeEnvelope
from arena.adapters.websocket.messages import ErrorBody, WelcomeBody
from arena.sdk._events import ErrorEvent
from arena.sdk._session import MAX_FRAME_BYTES, Session


class _FakeWs:
    def __init__(self, frames: list[str]) -> None:
        self.frames = list(frames)
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        return self.frames.pop(0)

    async def close(self) -> None:
        pass


def _welcome() -> str:
    return dumps(
        WelcomeEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            match_id="m",
            seat=0,
            payload=WelcomeBody(
                match_id="m",
                game_id="tictactoe",
                game_schema_version=1,
                seat=0,
                lifecycle="created",
                schema_version=WIRE_SCHEMA_VERSION,
                negotiated_schema_version=WIRE_SCHEMA_VERSION,
                resume_token="tok",
                per_turn_deadline_ms=1000,
                per_action_retry_budget=1,
                disconnect_grace_ms=1000,
                players=[],
                match_config={},
            ),
        )
    )


def _error() -> str:
    return dumps(
        ErrorEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            match_id="m",
            payload=ErrorBody(code="x", message="y"),
        )
    )


def test_the_sdk_accepts_frames_larger_than_the_websockets_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_connect(url: str, **kwargs: Any) -> _FakeWs:
        captured.update(kwargs)
        return _FakeWs([_welcome()])

    monkeypatch.setattr(session_module, "_ws_connect", fake_connect)
    asyncio.run(Session.connect("ws://x/matches/m/play?seat=0", 0))
    # A long match's match_finished is ~2 MB; the websockets default is 1 MiB.
    assert captured["max_size"] == MAX_FRAME_BYTES >= 16 * 1024 * 1024


def test_unknown_and_unhandled_message_types_are_skipped() -> None:
    unknown = json.dumps(
        {"type": "from_the_future", "schema_version": 3, "payload": {}}
    )
    spectator_only = json.dumps(
        {
            "type": "spectator_welcome",
            "schema_version": 3,
            "match_id": "m",
            "payload": {
                "match_id": "m",
                "game_id": "tictactoe",
                "game_schema_version": 1,
                "lifecycle": "created",
                "schema_version": 3,
                "negotiated_schema_version": 3,
                "players": [],
                "turn_count": 0,
                "transcript": None,
            },
        }
    )
    ws = _FakeWs([unknown, spectator_only, _error()])
    session = Session(ws, WelcomeEnvelope.model_validate(json.loads(_welcome())).payload)  # type: ignore[arg-type]
    event = asyncio.run(session.recv())
    assert isinstance(event, ErrorEvent)


def test_hello_is_readable_by_every_server_version_the_sdk_supports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A v3 server refuses an envelope stamped 4 before it reads the supported
    list, so the hello carries the lowest listed version; later frames carry the
    negotiated one."""

    fake = _FakeWs([_welcome()])

    async def fake_connect(url: str, **kwargs: Any) -> _FakeWs:
        return fake

    monkeypatch.setattr(session_module, "_ws_connect", fake_connect)

    async def run() -> None:
        session = await Session.connect("ws://x/matches/m/play?seat=0", 0)
        await session.send_action({"cell": 0})

    asyncio.run(run())
    hello, action = (json.loads(frame) for frame in fake.sent)
    assert hello["type"] == "hello"
    assert hello["schema_version"] == min(session_module.SUPPORTED_SCHEMA_VERSIONS) == 1
    assert action["type"] == "action_response"
    assert action["schema_version"] == WIRE_SCHEMA_VERSION
