"""Tests for Tic-Tac-Toe state models and board helpers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arena.games.tictactoe import (
    EMPTY_CELL,
    SEAT0_MARK,
    SEAT1_MARK,
    TicTacToeState,
    mark_for_seat,
)


def test_tictactoe_state_is_a_frozen_minimal_domain_object() -> None:
    state = TicTacToeState(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    assert state.current_seat == 0
    assert state.board[0][0] == EMPTY_CELL

    with pytest.raises(FrozenInstanceError):
        state.current_seat = 1  # type: ignore[misc]


def test_tictactoe_state_values_are_comparable() -> None:
    board = (
        (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        (EMPTY_CELL, SEAT0_MARK, EMPTY_CELL),
        (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
    )

    assert TicTacToeState(board=board, current_seat=1) == TicTacToeState(
        board=board,
        current_seat=1,
    )


def test_tictactoe_state_rejects_non_rectangular_boards() -> None:
    with pytest.raises(ValueError):
        TicTacToeState(
            board=((EMPTY_CELL, EMPTY_CELL, EMPTY_CELL), (EMPTY_CELL, EMPTY_CELL), (EMPTY_CELL,)),
            current_seat=0,
        )


@pytest.mark.parametrize("cell", [3, "1", True])
def test_tictactoe_state_rejects_invalid_cell_values(cell: object) -> None:
    with pytest.raises(ValueError):
        TicTacToeState(
            board=(
                (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                (EMPTY_CELL, cell, EMPTY_CELL),
                (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            ),  # type: ignore[arg-type]
            current_seat=0,
        )


@pytest.mark.parametrize("seat", [2, -1, "0", True])
def test_tictactoe_state_rejects_invalid_active_seat_values(seat: object) -> None:
    with pytest.raises(ValueError):
        TicTacToeState(
            board=(
                (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            ),
            current_seat=seat,  # type: ignore[arg-type]
        )


def test_mark_for_seat_maps_tictactoe_seats_to_board_values() -> None:
    assert mark_for_seat(0) == SEAT0_MARK
    assert mark_for_seat(1) == SEAT1_MARK


def test_mark_for_seat_rejects_out_of_range_seats() -> None:
    with pytest.raises(ValueError):
        mark_for_seat(2)
