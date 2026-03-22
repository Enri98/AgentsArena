"""Immutable Connect 4 board state models and helpers.

Board conventions:
- `0` means an empty cell
- `1` means a disc from seat `0`
- `2` means a disc from seat `1`
- row `0` is the top row
- columns increase from left to right
"""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.types import Seat

EMPTY_CELL = 0
SEAT0_DISC = 1
SEAT1_DISC = 2

VALID_SEATS = (0, 1)
VALID_DISC_VALUES = {EMPTY_CELL, SEAT0_DISC, SEAT1_DISC}

Connect4Board = tuple[tuple[int, ...], ...]


def disc_for_seat(seat: Seat) -> int:
    """Return the stored board value for a Connect 4 seat."""

    if seat == 0:
        return SEAT0_DISC
    if seat == 1:
        return SEAT1_DISC
    raise ValueError("Connect 4 supports only seats 0 and 1")


@dataclass(frozen=True)
class Connect4State:
    """Minimal immutable state for a Connect 4 position."""

    board: Connect4Board
    current_seat: Seat

    def __post_init__(self) -> None:
        if not self.board:
            raise ValueError("board must contain at least one row")

        row_length = len(self.board[0])
        if row_length == 0:
            raise ValueError("board rows must contain at least one column")

        for row in self.board:
            if len(row) != row_length:
                raise ValueError("board must be rectangular")
            for cell in row:
                if type(cell) is not int or cell not in VALID_DISC_VALUES:
                    raise ValueError("board cells must be integer Connect 4 disc values")

        if type(self.current_seat) is not int or self.current_seat not in VALID_SEATS:
            raise ValueError("current_seat must be 0 or 1")


__all__ = [
    "EMPTY_CELL",
    "SEAT0_DISC",
    "SEAT1_DISC",
    "Connect4Board",
    "Connect4State",
    "disc_for_seat",
]
