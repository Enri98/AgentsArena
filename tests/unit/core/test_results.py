"""Tests for core rule-result abstractions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arena.core.results import Draw, RuleResult, Win


def test_result_symbols_are_importable() -> None:
    assert RuleResult.__name__ == "RuleResult"
    assert Win.__name__ == "Win"
    assert Draw.__name__ == "Draw"


def test_win_is_a_frozen_generic_result() -> None:
    result = Win(seat=1)

    assert isinstance(result, RuleResult)
    assert result.seat == 1
    assert result.result_type == "Win"

    with pytest.raises(FrozenInstanceError):
        result.seat = 0  # type: ignore[misc]


def test_draw_is_a_frozen_generic_result() -> None:
    result = Draw()

    assert isinstance(result, RuleResult)
    assert result.result_type == "Draw"


def test_result_values_are_comparable() -> None:
    assert Win(seat=0) == Win(seat=0)
    assert Win(seat=0) != Win(seat=1)
    assert Draw() == Draw()
