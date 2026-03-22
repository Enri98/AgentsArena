"""Tests for Connect 4 action models."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arena.core.actions import Action
from arena.games.connect4 import DropDisc


def test_drop_disc_is_a_frozen_seat_agnostic_action() -> None:
    action = DropDisc(column=3)

    assert isinstance(action, Action)
    assert action.column == 3
    assert action.action_type == "DropDisc"

    with pytest.raises(FrozenInstanceError):
        action.column = 4  # type: ignore[misc]


@pytest.mark.parametrize("column", [-1, "3", True])
def test_drop_disc_rejects_invalid_column_values(column: object) -> None:
    with pytest.raises(ValueError):
        DropDisc(column=column)  # type: ignore[arg-type]
