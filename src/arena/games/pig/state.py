"""Immutable Pig game state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.types import Seat

VALID_SEATS = (0, 1)
#: The config's bound, enforced again on load.
MAX_TARGET_SCORE = 1000


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
        if type(self.target_score) is not int or not 1 <= self.target_score <= MAX_TARGET_SCORE:
            raise ValueError(f"target_score must be an integer in 1..{MAX_TARGET_SCORE}")
        winners = [seat for seat in VALID_SEATS if self.scores[seat] >= self.target_score]
        if len(winners) > 1:
            raise ValueError("only one seat can reach the target")
        if winners and (
            self.current_seat != winners[0] or self.turn_total or self.roll_pending
        ):
            # Banking ends the match with the winner still to move, as Nim does.
            raise ValueError("a finished match rests with the winner to move and no turn open")


__all__: Sequence[str] = ["PigState", "VALID_SEATS"]
