"""Immutable Pig game state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.types import Seat

VALID_SEATS = (0, 1)


@dataclass(frozen=True)
class PigState:
    """Minimal immutable state for a Pig position.

    ``roll_pending`` marks a chance node: the current seat chose to roll and the
    die has not landed yet. ``target_score`` is carried in state so terminality
    and the winner are derivable from state alone.
    """

    scores: tuple[int, int]
    current_seat: Seat
    turn_total: int
    roll_pending: bool
    target_score: int

    def __post_init__(self) -> None:
        if len(self.scores) != 2:
            raise ValueError("scores must hold exactly one entry per seat")
        for score in self.scores:
            if type(score) is not int or score < 0:
                raise ValueError("every score must be a non-negative integer")
        if type(self.current_seat) is not int or self.current_seat not in VALID_SEATS:
            raise ValueError("current_seat must be 0 or 1")
        if type(self.turn_total) is not int or self.turn_total < 0:
            raise ValueError("turn_total must be a non-negative integer")
        if type(self.roll_pending) is not bool:
            raise ValueError("roll_pending must be a bool")
        if type(self.target_score) is not int or self.target_score < 1:
            raise ValueError("target_score must be a positive integer")


__all__: Sequence[str] = ["PigState", "VALID_SEATS"]
