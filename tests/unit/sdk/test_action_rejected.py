"""The SDK handles action_rejected (review of Phase 39 Slice 2).

It used to raise "Unhandled envelope type: 'action_rejected'", killing the client
on any rejected move, even though the server keeps the turn open for a retry.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from arena.adapters.websocket import loads
from arena.sdk._connect import _run_session
from arena.sdk._events import (
    ActionRejectedEvent,
    MatchFinishedEvent,
    ObservationEvent,
)
from arena.sdk._session import _env_to_event


def test_action_rejected_becomes_an_event() -> None:
    raw = (
        '{"type": "action_rejected", "schema_version": 3, "match_id": "m", "seat": 0, '
        '"turn_id": "t", "payload": {"turn_id": "t", "error": {"code": "illegal_action", '
        '"message": "no", "details": {}}, "retries_remaining": 2}}'
    )
    event = _env_to_event(loads(raw))
    assert isinstance(event, ActionRejectedEvent)
    assert event.body.retries_remaining == 2


def test_the_callback_loop_chooses_again_after_a_rejection() -> None:
    observation = SimpleNamespace(observation={"n": 1})
    events = [
        ObservationEvent(body=SimpleNamespace(observation_request=observation)),
        ActionRejectedEvent(body=SimpleNamespace(retries_remaining=2)),
        MatchFinishedEvent(body=SimpleNamespace(result={"ok": True}, transcript="t")),
    ]
    sent: list[dict] = []

    class _Session:
        async def recv(self):
            return events.pop(0)

        async def send_action(self, action):
            sent.append(action)

    calls: list[object] = []

    def choose(obs):
        calls.append(obs)
        return {"attempt": len(calls)}

    result, transcript = asyncio.run(_run_session(_Session(), choose))
    assert result == {"ok": True} and transcript == "t"
    assert calls == [observation, observation]
    assert sent == [{"attempt": 1}, {"attempt": 2}]
