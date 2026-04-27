"""Tests for Tic-Tac-Toe action models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arena.core.actions import Action
from arena.games.tictactoe import PlaceMark


def test_place_mark_is_a_frozen_seat_agnostic_action() -> None:
    action = PlaceMark(row=1, column=2)

    assert isinstance(action, Action)
    assert action.row == 1
    assert action.column == 2
    assert action.action_type == "PlaceMark"

    with pytest.raises(FrozenInstanceError):
        action.row = 0  # type: ignore[misc]


@pytest.mark.parametrize("row, column", [(-1, 0), (0, -1), ("1", 0), (0, True)])
def test_place_mark_rejects_invalid_coordinate_values(row: object, column: object) -> None:
    with pytest.raises(ValueError):
        PlaceMark(row=row, column=column)  # type: ignore[arg-type]
