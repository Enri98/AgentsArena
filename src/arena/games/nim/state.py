"""Immutable Nim game state.

The state is the tuple of pile sizes and the seat whose turn it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.types import Seat

NimPiles = tuple[int, ...]

VALID_SEATS = (0, 1)


@dataclass(frozen=True)
class NimState:
    """Minimal immutable state for a Nim position."""

    piles: NimPiles
    current_seat: Seat

    def __post_init__(self) -> None:
        if not self.piles:
            raise ValueError("piles must be a non-empty tuple of non-negative integers")
        for size in self.piles:
            if type(size) is not int or size < 0:
                raise ValueError("every pile size must be a non-negative integer")
        if type(self.current_seat) is not int or self.current_seat not in VALID_SEATS:
            raise ValueError("current_seat must be 0 or 1")


__all__: Sequence[str] = ["NimPiles", "NimState", "VALID_SEATS"]
