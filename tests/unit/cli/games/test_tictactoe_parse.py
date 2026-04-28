"""Tests for arena.cli.games.tictactoe.parse_input."""

from __future__ import annotations

from arena.cli.games.tictactoe import parse_input
from arena.games.tictactoe import PlaceMark, TicTacToeGameDefinition
from arena.match.local_match import apply_match_action, start_match


def _observation(seat: int = 0):
    from arena.games.tictactoe import TicTacToeConfig
    match = start_match(TicTacToeGameDefinition, TicTacToeConfig())
    return TicTacToeGameDefinition.rules_engine.observation(match.state, seat)


def test_key_1_maps_to_top_left():
    obs = _observation()
    result = parse_input("1\n", obs)
    assert result == PlaceMark(row=0, column=0)


def test_key_9_maps_to_bottom_right():
    obs = _observation()
    result = parse_input("9\n", obs)
    assert result == PlaceMark(row=2, column=2)


def test_key_5_maps_to_center():
    obs = _observation()
    result = parse_input("5\n", obs)
    assert result == PlaceMark(row=1, column=1)


def test_empty_line_returns_none():
    obs = _observation()
    assert parse_input("", obs) is None
    assert parse_input("   \n", obs) is None


def test_non_integer_returns_none():
    obs = _observation()
    assert parse_input("abc\n", obs) is None


def test_out_of_range_returns_none():
    obs = _observation()
    assert parse_input("0\n", obs) is None
    assert parse_input("10\n", obs) is None


def test_occupied_cell_returns_none():
    from arena.games.tictactoe import TicTacToeConfig
    match = start_match(TicTacToeGameDefinition, TicTacToeConfig())
    m = apply_match_action(match, 0, PlaceMark(row=0, column=0))
    obs = TicTacToeGameDefinition.rules_engine.observation(m.state, 1)
    assert parse_input("1\n", obs) is None


def test_whitespace_trimmed():
    obs = _observation()
    result = parse_input("  3  \n", obs)
    assert result == PlaceMark(row=0, column=2)
