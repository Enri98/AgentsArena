"""Tests for PigPromptBuilder prompt rendering and response parsing."""

from __future__ import annotations

import json

from arena.agents.ollama._adapters import get_ollama_adapter
from arena.agents.ollama.pig import PigPromptBuilder
from arena.games.pig import HOLD, ROLL, PigMove, PigRulesEngine, PigState

ENGINE = PigRulesEngine()
BUILDER = PigPromptBuilder()


def _obs(turn_total: int = 0, scores: tuple[int, int] = (0, 0), target: int = 50):
    state = PigState(
        scores=scores, current_seat=0, turn_total=turn_total, roll_pending=False,
        target_score=target,
    )
    return ENGINE.observation(state, 0)


def test_prompt_states_scores_turn_total_and_legal_choices() -> None:
    messages = BUILDER.build_messages(_obs(turn_total=8, scores=(20, 35)))
    user = messages[-1]["content"]

    assert messages[0]["role"] == "system"
    assert "Your banked score: 20 (need 30 more)" in user
    assert "Opponent banked score: 35 (needs 15 more)" in user
    assert "Your turn total so far: 8" in user
    assert json.dumps(["roll", "hold"]) in user


def test_prompt_flags_a_winning_hold() -> None:
    user = BUILDER.build_messages(_obs(turn_total=12, scores=(40, 0)))[-1]["content"]
    assert "Holding now reaches the target" in user


def test_retry_feedback_is_appended() -> None:
    user = BUILDER.build_messages(_obs(), retry_feedback=("bad json",))[-1]["content"]
    assert "Previous attempts were rejected" in user
    assert "bad json" in user


def test_parses_legal_choices_case_insensitively() -> None:
    obs = _obs(turn_total=5)
    assert BUILDER.parse_response('{"choice": "HOLD"}', obs) == PigMove(choice=HOLD)
    assert BUILDER.parse_response('{"thought": "x", "choice": "roll"}', obs) == PigMove(
        choice=ROLL
    )


def test_rejects_illegal_or_malformed_responses() -> None:
    opening = _obs(turn_total=0)
    assert BUILDER.parse_response('{"choice": "hold"}', opening) is None  # must roll first
    assert BUILDER.parse_response('{"choice": "pass"}', opening) is None
    assert BUILDER.parse_response("not json", opening) is None
    assert BUILDER.parse_response('["roll"]', opening) is None
    assert BUILDER.parse_response('{"choice": 1}', opening) is None


def test_format_spec_enumerates_choices() -> None:
    spec = BUILDER.format_spec()
    assert spec["properties"]["choice"]["enum"] == ["roll", "hold"]
    assert set(spec["required"]) == {"thought", "choice"}


def test_registered_with_the_ollama_adapter_registry() -> None:
    assert get_ollama_adapter("pig").prompt_builder_factory is PigPromptBuilder
