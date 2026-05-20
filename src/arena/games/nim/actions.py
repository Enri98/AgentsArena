"""Nim action model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.actions import Action


@dataclass(frozen=True)
class TakeObjects(Action):
    """Take *count* objects from *pile_index*."""

    pile_index: int
    count: int

    def __post_init__(self) -> None:
        if type(self.pile_index) is not int or self.pile_index < 0:
            raise ValueError("pile_index must be a non-negative integer")
        if type(self.count) is not int or self.count < 1:
            raise ValueError("count must be a positive integer")


__all__: Sequence[str] = ["TakeObjects"]
