"""Seat-agnostic Connect 4 action models."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.actions import Action


@dataclass(frozen=True)
class DropDisc(Action):
    """Drop a disc into the selected zero-based column."""

    column: int

    def __post_init__(self) -> None:
        if type(self.column) is not int or self.column < 0:
            raise ValueError("column must be a non-negative integer")


__all__ = ["DropDisc"]
