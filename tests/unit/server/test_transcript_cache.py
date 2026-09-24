"""The server's incremental per-viewer transcripts (third review, Phase 38).

They must equal the runtime's own per-viewer dump at every step, and a warm
rebuild must not redo the linear work: that is what made attach/detach loops a
denial of service.
"""

from __future__ import annotations

import dataclasses
import time

import pytest

from arena.match import apply_match_action, start_match
from arena.runtime.models import PlayerRecord
from arena.runtime.payloads import dump_runtime_transcript
from arena.runtime.session import Arena
from arena.server.runtime_bridge import _build_transcript_payload, forget_match_transcripts
from arena.testing.hidden_factory import SecretsPass, build_secrets_game_definition


def _session(definition, config, match_id: str):
    arena = Arena()
    session = arena.create_session(
        definition,
        config,
        [PlayerRecord(player_id="p0", seat=0), PlayerRecord(player_id="p1", seat=1)],
        {},
        match_id=match_id,
    )
    return dataclasses.replace(session, local_match=start_match(definition, config, seed=5))


def _step(session):
    match = session.local_match
    seat = match.rules_engine.current_seat(match.state)
    action = match.rules_engine.legal_actions(match.state, seat)[0]
    return dataclasses.replace(session, local_match=apply_match_action(match, seat, action))


@pytest.mark.parametrize("game", ["secrets", "pig"])
def test_incremental_transcripts_equal_the_runtime_dump_at_every_step(game: str) -> None:
    from arena.games.pig import PigConfig, PigGameDefinition

    if game == "secrets":
        definition = build_secrets_game_definition()
        config = definition.config_type(max_turns=6)
    else:
        definition, config = PigGameDefinition, PigConfig(target_score=10)
    session = _session(definition, config, f"cache-{game}")
    try:
        for _ in range(5):
            if session.local_match.rules_engine.is_terminal(session.local_match.state):
                break
            for viewer in (0, 1, None):
                assert _build_transcript_payload(session, viewer).model_dump(
                    mode="json"
                ) == dump_runtime_transcript(session, viewer=viewer)
            session = _step(session)
    finally:
        forget_match_transcripts(session.match_id)


def test_a_warm_rebuild_of_a_long_match_is_cheap() -> None:
    definition = build_secrets_game_definition()
    config = definition.config_type(max_turns=1500)
    session = _session(definition, config, "cache-long")
    match = session.local_match
    for turn in range(1500):
        match = apply_match_action(match, turn % 2, SecretsPass())
    session = dataclasses.replace(session, local_match=match)
    try:
        started = time.perf_counter()
        _build_transcript_payload(session, None)
        cold = time.perf_counter() - started

        started = time.perf_counter()
        for _ in range(5):
            _build_transcript_payload(session, None)
        warm = (time.perf_counter() - started) / 5
    finally:
        forget_match_transcripts(session.match_id)

    assert warm < cold / 4, (cold, warm)
