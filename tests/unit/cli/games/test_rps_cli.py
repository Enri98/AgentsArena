"""The Rock-Paper-Scissors CLI adapter."""

from __future__ import annotations

import pytest

from arena.cli.games import rps as rps_cli
from arena.games.rps import RpsConfig, RpsRulesEngine, Throw

ENGINE = RpsRulesEngine()


def test_input_accepts_words_and_shortcuts() -> None:
    obs = ENGINE.observation(ENGINE.initial_state(RpsConfig()), 0)
    assert rps_cli.parse_input("R", obs) == Throw("rock")
    assert rps_cli.parse_input(" scissors ", obs) == Throw("scissors")
    assert rps_cli.parse_input("lizard", obs) is None


def test_scripted_throws_parse_and_bad_ones_fail() -> None:
    expected = [Throw("rock"), Throw("paper"), Throw("scissors")]
    assert rps_cli._parse_scripted("rock, p ,s") == expected
    with pytest.raises(ValueError):
        rps_cli._parse_scripted("rock,spock")


def test_the_state_renders_the_score_and_last_round() -> None:
    text = rps_cli.render_state_plain(
        {
            "wins": [2, 1],
            "rounds_played": 4,
            "target_wins": 3,
            "max_rounds": 20,
            "last_round": {"throws": ["rock", "rock"], "winner": None},
        }
    )
    assert "Seat 0: 2" in text and "rock vs rock (tie)" in text
