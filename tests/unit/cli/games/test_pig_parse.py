"""Tests for the Pig CLI adapter: parsing, rendering, and registration."""

from __future__ import annotations

import argparse

import pytest

from arena.cli.games import get_cli_adapter
from arena.cli.games.pig import parse_input, render_state, render_state_plain
from arena.games.pig import HOLD, ROLL, PigConfig, PigMove, PigRulesEngine, PigState
from arena.mcp.schemas import PIG_ACTION_SCHEMA, game_action_schema

ENGINE = PigRulesEngine()


def _obs(turn_total: int):
    state = PigState(
        scores=(3, 9), current_seat=0, turn_total=turn_total, roll_pending=False,
        target_score=50,
    )
    return ENGINE.observation(state, 0)


@pytest.mark.parametrize("line", ["roll", "ROLL", " r "])
def test_roll_aliases(line: str) -> None:
    assert parse_input(line, _obs(0)) == PigMove(choice=ROLL)


def test_hold_is_refused_until_there_is_something_to_hold() -> None:
    assert parse_input("hold", _obs(0)) is None
    assert parse_input("h", _obs(4)) == PigMove(choice=HOLD)


@pytest.mark.parametrize("line", ["", "pass", "roll hold"])
def test_garbage_is_rejected(line: str) -> None:
    assert parse_input(line, _obs(4)) is None


def test_scripted_parser() -> None:
    adapter = get_cli_adapter("pig")
    assert adapter.scripted_parser("roll, r ,hold") == [
        PigMove(choice=ROLL), PigMove(choice=ROLL), PigMove(choice=HOLD),
    ]
    with pytest.raises(ValueError):
        adapter.scripted_parser("roll,jump")


def test_config_factory_reads_pig_target() -> None:
    adapter = get_cli_adapter("pig")
    assert adapter.config_factory(argparse.Namespace(pig_target=30)) == PigConfig(target_score=30)


def test_renderers_show_scores_and_turn_total() -> None:
    payload = {"scores": [3, 9], "current_seat": 1, "turn_total": 7, "roll_pending": False,
               "target_score": 50}
    plain = render_state_plain(payload)
    assert "Target: 50" in plain
    assert "Seat 0: 3" in plain and "> Seat 1: 9" in plain
    assert "Turn total: 7" in plain
    assert "\x1b[" not in plain
    assert "\x1b[" in render_state(payload)


def test_mcp_schema_is_registered() -> None:
    assert game_action_schema("pig") is PIG_ACTION_SCHEMA
    assert PIG_ACTION_SCHEMA["required"] == ["choice"]
