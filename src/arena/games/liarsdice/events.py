"""Liar's Dice domain events.

Events are public unless they override ``visible_to``. ``DiceDealt`` is the one
private event: a seat is told its own hand and nobody else is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.events import DomainEvent
from arena.core.types import Seat


@dataclass(frozen=True)
class RoundRolled(DomainEvent):
    """A new round's dice were rolled (public: the counts, not the faces)."""

    round_number: int
    dice_counts: list[int]


@dataclass(frozen=True)
class DiceDealt(DomainEvent):
    """Private to ``seat``: the hand it was dealt this round."""

    seat: Seat
    dice: list[int]

    def visible_to(self, viewer: Seat | None) -> bool:
        return viewer == self.seat


@dataclass(frozen=True)
class BidMade(DomainEvent):
    seat: Seat
    quantity: int
    face: int


@dataclass(frozen=True)
class BidCalled(DomainEvent):
    """``seat`` called the standing bid; both hands are revealed."""

    seat: Seat
    dice: list[list[int]]
    quantity: int
    face: int
    count: int
    loser: Seat


@dataclass(frozen=True)
class DieLost(DomainEvent):
    seat: Seat
    remaining: int


@dataclass(frozen=True)
class LiarsDiceMatchWon(DomainEvent):
    winner_seat: Seat


__all__: Sequence[str] = [
    "BidCalled",
    "BidMade",
    "DiceDealt",
    "DieLost",
    "LiarsDiceMatchWon",
    "RoundRolled",
]
