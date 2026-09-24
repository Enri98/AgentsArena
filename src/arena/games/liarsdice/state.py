"""Immutable Liar's Dice state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.types import Seat
from arena.games.liarsdice.actions import Bid

VALID_SEATS = (0, 1)

Hands = tuple[tuple[int, ...], tuple[int, ...]]


@dataclass(frozen=True)
class Showdown:
    """What a call revealed. Public: once called, both hands are on the table."""

    caller: Seat
    bid: Bid
    dice: Hands
    count: int
    loser: Seat


@dataclass(frozen=True)
class LiarsDiceState:
    """Minimal immutable state for a Liar's Dice position.

    ``dice`` is ``None`` while a roll is pending — a chance node at the start of
    every round. ``dice_counts`` is public; the dice themselves are private to
    their seat until a showdown. ``bids`` is the current round's history, oldest
    first; the last one stands.
    """

    dice: Hands | None
    dice_counts: tuple[int, int]
    bids: tuple[Bid, ...]
    current_seat: Seat
    round_number: int
    faces: int
    last_showdown: Showdown | None = None

    def __post_init__(self) -> None:
        if type(self.current_seat) is not int or self.current_seat not in VALID_SEATS:
            raise ValueError("current_seat must be 0 or 1")
        if len(self.dice_counts) != 2 or any(
            type(c) is not int or c < 0 for c in self.dice_counts
        ):
            raise ValueError("dice_counts must be two non-negative integers")
        if self.dice is not None:
            if len(self.dice) != 2:
                raise ValueError("dice must hold one hand per seat")
            for hand, count in zip(self.dice, self.dice_counts):
                if len(hand) != count:
                    raise ValueError("each hand must hold exactly dice_counts dice")
                if any(type(d) is not int or not 1 <= d <= self.faces for d in hand):
                    raise ValueError("every die shows a face in 1..faces")

    @property
    def standing_bid(self) -> Bid | None:
        return self.bids[-1] if self.bids else None


__all__: Sequence[str] = ["Hands", "LiarsDiceState", "Showdown", "VALID_SEATS"]
