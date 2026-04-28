"""Tests for arena.cli.games.connect4.parse_input."""

from __future__ import annotations

from arena.cli.games.connect4 import parse_input
from arena.games.connect4 import Connect4Config, Connect4GameDefinition, DropDisc
from arena.match.local_match import start_match


def _observation(config: Connect4Config | None = None, seat: int = 0):
    cfg = config or Connect4Config()
    match = start_match(Connect4GameDefinition, cfg)
    return Connect4GameDefinition.rules_engine.observation(match.state, seat)


def test_legal_column_returns_action():
    obs = _observation()
    result = parse_input("3\n", obs)
    assert result == DropDisc(column=3)


def test_empty_line_returns_none():
    obs = _observation()
    assert parse_input("", obs) is None
    assert parse_input("   \n", obs) is None


def test_non_integer_returns_none():
    obs = _observation()
    assert parse_input("abc\n", obs) is None


def test_negative_column_returns_none():
    obs = _observation()
    assert parse_input("-1\n", obs) is None


def test_out_of_range_column_returns_none():
    obs = _observation()
    assert parse_input("99\n", obs) is None


def test_full_column_returns_none():
    from arena.match.local_match import apply_match_action

    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    m = start_match(Connect4GameDefinition, cfg)
    for _ in range(4):
        seat = Connect4GameDefinition.rules_engine.current_seat(m.state)
        m = apply_match_action(m, seat, DropDisc(column=0))

    seat = Connect4GameDefinition.rules_engine.current_seat(m.state)
    obs = Connect4GameDefinition.rules_engine.observation(m.state, seat)
    assert parse_input("0\n", obs) is None


def test_whitespace_trimmed():
    obs = _observation()
    result = parse_input("  2  \n", obs)
    assert result == DropDisc(column=2)
