"""Tests for Connect 4 state models and board helpers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arena.games.connect4 import (
    EMPTY_CELL,
    SEAT0_DISC,
    SEAT1_DISC,
    Connect4State,
    disc_for_seat,
)


def test_connect4_state_is_a_frozen_minimal_domain_object() -> None:
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    assert state.current_seat == 0
    assert state.board[0][0] == EMPTY_CELL

    with pytest.raises(FrozenInstanceError):
        state.current_seat = 1  # type: ignore[misc]


def test_connect4_state_values_are_comparable() -> None:
    board = (
        (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        (SEAT0_DISC, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
    )

    assert Connect4State(board=board, current_seat=1) == Connect4State(board=board, current_seat=1)


def test_connect4_state_rejects_non_rectangular_boards() -> None:
    with pytest.raises(ValueError):
        Connect4State(
            board=((EMPTY_CELL, EMPTY_CELL), (EMPTY_CELL,)),
            current_seat=0,
        )


@pytest.mark.parametrize("cell", [3, "1", True])
def test_connect4_state_rejects_invalid_cell_values(cell: object) -> None:
    with pytest.raises(ValueError):
        Connect4State(
            board=((EMPTY_CELL, EMPTY_CELL), (EMPTY_CELL, cell)),  # type: ignore[arg-type]
            current_seat=0,
        )


@pytest.mark.parametrize("seat", [2, -1, "0", True])
def test_connect4_state_rejects_invalid_active_seat_values(seat: object) -> None:
    with pytest.raises(ValueError):
        Connect4State(
            board=((EMPTY_CELL, EMPTY_CELL), (EMPTY_CELL, EMPTY_CELL)),
            current_seat=seat,  # type: ignore[arg-type]
        )


def test_disc_for_seat_maps_connect4_seats_to_board_values() -> None:
    assert disc_for_seat(0) == SEAT0_DISC
    assert disc_for_seat(1) == SEAT1_DISC


def test_disc_for_seat_rejects_out_of_range_seats() -> None:
    with pytest.raises(ValueError):
        disc_for_seat(2)
