"""Seat-agnostic Tic-Tac-Toe action models."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.actions import Action


@dataclass(frozen=True)
class PlaceMark(Action):
    """Place a mark into the selected zero-based board cell."""

    row: int
    column: int

    def __post_init__(self) -> None:
        if type(self.row) is not int or self.row < 0:
            raise ValueError("row must be a non-negative integer")
        if type(self.column) is not int or self.column < 0:
            raise ValueError("column must be a non-negative integer")


__all__ = ["PlaceMark"]
