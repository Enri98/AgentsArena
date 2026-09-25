"""The UI adapter renders simultaneous rounds (Phase 41)."""

from __future__ import annotations

import json
import random

from arena.adapters.in_process import TypedPayloadPolicyAdapter
from arena.games import build_default_registry
from arena.runtime.models import PlayerRecord
from arena.runtime.payloads import dump_runtime_transcript, dump_session_status
from arena.runtime.session import Arena
from arena.ui.payloads import build_match_screen

RPS = build_default_registry().get("rps")


class _Random:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def select_action(self, observation):  # type: ignore[no-untyped-def]
        return self.rng.choice(observation.legal_actions)


def test_a_joint_turn_renders_with_both_actions() -> None:
    arena = Arena()
    session = arena.run_session(
        arena.create_session(
            RPS,
            RPS.config_type(),
            [PlayerRecord("p0", 0), PlayerRecord("p1", 1)],
            {
                0: TypedPayloadPolicyAdapter(RPS, _Random(1)),
                1: TypedPayloadPolicyAdapter(RPS, _Random(2)),
            },
        )
    )
    screen = build_match_screen(
        status_payload=json.loads(json.dumps(dump_session_status(session))),
        transcript_payload=json.loads(json.dumps(dump_runtime_transcript(session))),
    )
    first = screen["transcript"]["turns"][0]
    assert first["kind"] == "joint"
    assert first["seat"] is None
    assert set(first["actions"]) == {"0", "1"}
