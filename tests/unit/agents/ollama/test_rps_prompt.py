"""The Rock-Paper-Scissors Ollama prompt builder."""

from __future__ import annotations

import json

from arena.agents.ollama.rps import RpsPromptBuilder
from arena.games.rps import RoundResult, RpsConfig, RpsRulesEngine, RpsState, Throw

ENGINE = RpsRulesEngine()


def _observation(seat: int = 1):  # type: ignore[no-untyped-def]
    state = RpsState(
        wins=(1, 0),
        rounds_played=2,
        target_wins=3,
        max_rounds=20,
        last_round=RoundResult(("paper", "rock"), 0),
    )
    return ENGINE.observation(state, seat)


def test_the_prompt_states_the_score_and_the_last_round_from_the_seats_side() -> None:
    messages = RpsPromptBuilder().build_messages(_observation(seat=1))
    user = messages[-1]["content"]
    assert "Score: you 0, opponent 1" in user
    assert "you threw rock, the opponent threw paper (the opponent won it)" in user


def test_a_first_round_prompt_has_no_last_round() -> None:
    obs = ENGINE.observation(ENGINE.initial_state(RpsConfig()), 0)
    assert "Last round" not in RpsPromptBuilder().build_messages(obs)[-1]["content"]


def test_responses_parse_to_legal_throws_only() -> None:
    builder = RpsPromptBuilder()
    obs = _observation()
    assert builder.parse_response(json.dumps({"shape": " Paper "}), obs) == Throw("paper")
    assert builder.parse_response(json.dumps({"shape": "lizard"}), obs) is None
    assert builder.parse_response("not json", obs) is None
    assert builder.parse_response(json.dumps(["rock"]), obs) is None
    assert builder.format_spec()["properties"]["shape"]["enum"] == ["rock", "paper", "scissors"]
