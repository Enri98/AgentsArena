"""Tests for arena.cli.policies.HumanPolicy."""

from __future__ import annotations

import io

import pytest

from arena.cli.games.connect4 import parse_input as c4_parse
from arena.cli.policies import HumanPolicy, HumanQuit
from arena.games.connect4 import Connect4Config, Connect4GameDefinition, DropDisc
from arena.match.local_match import apply_match_action, start_match


def _c4_observation(config: Connect4Config | None = None, seat: int = 0):
    cfg = config or Connect4Config()
    match = start_match(Connect4GameDefinition, cfg)
    return Connect4GameDefinition.rules_engine.observation(match.state, seat)


def _make_policy(lines: str) -> tuple[HumanPolicy, io.StringIO]:
    stdin = io.StringIO(lines)
    stdout = io.StringIO()
    policy = HumanPolicy(c4_parse, stdin=stdin, stdout=stdout)
    return policy, stdout


def test_legal_input_returns_action():
    policy, _ = _make_policy("3\n")
    obs = _c4_observation()
    result = policy.select_action(obs)
    assert result == DropDisc(column=3)


def test_illegal_syntax_retries_then_succeeds():
    policy, stdout = _make_policy("abc\n3\n")
    obs = _c4_observation()
    result = policy.select_action(obs)
    assert result == DropDisc(column=3)
    assert "Invalid input" in stdout.getvalue()


def test_out_of_range_retries_then_succeeds():
    policy, stdout = _make_policy("99\n2\n")
    obs = _c4_observation()
    result = policy.select_action(obs)
    assert result == DropDisc(column=2)
    assert "Invalid input" in stdout.getvalue()


def test_full_column_retries_then_succeeds():
    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    m = start_match(Connect4GameDefinition, cfg)
    for _ in range(4):
        seat = Connect4GameDefinition.rules_engine.current_seat(m.state)
        m = apply_match_action(m, seat, DropDisc(column=0))
    seat = Connect4GameDefinition.rules_engine.current_seat(m.state)
    obs = Connect4GameDefinition.rules_engine.observation(m.state, seat)

    policy, stdout = _make_policy("0\n1\n")
    result = policy.select_action(obs)
    assert result == DropDisc(column=1)
    assert "Invalid input" in stdout.getvalue()


def test_q_raises_human_quit():
    policy, _ = _make_policy("q\n")
    obs = _c4_observation()
    with pytest.raises(HumanQuit) as exc_info:
        policy.select_action(obs)
    assert exc_info.value.reason == "user_quit"


def test_quit_raises_human_quit():
    policy, _ = _make_policy("quit\n")
    obs = _c4_observation()
    with pytest.raises(HumanQuit) as exc_info:
        policy.select_action(obs)
    assert exc_info.value.reason == "user_quit"


def test_eof_raises_human_quit():
    policy, _ = _make_policy("")
    obs = _c4_observation()
    with pytest.raises(HumanQuit) as exc_info:
        policy.select_action(obs)
    assert exc_info.value.reason == "user_quit"


def test_keyboard_interrupt_raises_human_quit():
    class _InterruptingStdin:
        def readline(self) -> str:
            raise KeyboardInterrupt

    stdout = io.StringIO()
    policy = HumanPolicy(c4_parse, stdin=_InterruptingStdin(), stdout=stdout)
    obs = _c4_observation()
    with pytest.raises(HumanQuit) as exc_info:
        policy.select_action(obs)
    assert exc_info.value.reason == "user_interrupt"
