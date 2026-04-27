"""Immutable Tic-Tac-Toe board state models and helpers.

Board conventions:
- `0` means an empty cell
- `1` means a mark from seat `0`
- `2` means a mark from seat `1`
- row `0` is the top row
- columns increase from left to right
"""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.types import Seat

EMPTY_CELL = 0
SEAT0_MARK = 1
SEAT1_MARK = 2

VALID_SEATS = (0, 1)
VALID_MARK_VALUES = {EMPTY_CELL, SEAT0_MARK, SEAT1_MARK}
BOARD_SIZE = 3

TicTacToeBoard = tuple[tuple[int, ...], ...]


def mark_for_seat(seat: Seat) -> int:
    """Return the stored board value for a Tic-Tac-Toe seat."""

    if seat == 0:
        return SEAT0_MARK
    if seat == 1:
        return SEAT1_MARK
    raise ValueError("Tic-Tac-Toe supports only seats 0 and 1")


@dataclass(frozen=True)
class TicTacToeState:
    """Minimal immutable state for a Tic-Tac-Toe position."""

    board: TicTacToeBoard
    current_seat: Seat

    def __post_init__(self) -> None:
        if not self.board:
            raise ValueError("board must contain exactly 3 rows")

        if len(self.board) != BOARD_SIZE:
            raise ValueError("board must contain exactly 3 rows")

        row_length = len(self.board[0])
        if row_length != BOARD_SIZE:
            raise ValueError("board rows must contain exactly 3 columns")

        for row in self.board:
            if len(row) != row_length:
                raise ValueError("board must be rectangular")
            for cell in row:
                if type(cell) is not int or cell not in VALID_MARK_VALUES:
                    raise ValueError("board cells must be integer Tic-Tac-Toe mark values")

        if type(self.current_seat) is not int or self.current_seat not in VALID_SEATS:
            raise ValueError("current_seat must be 0 or 1")


__all__ = [
    "BOARD_SIZE",
    "EMPTY_CELL",
    "SEAT0_MARK",
    "SEAT1_MARK",
    "TicTacToeBoard",
    "TicTacToeState",
    "mark_for_seat",
]
