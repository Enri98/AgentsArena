"""Liar's Dice actions and the chance outcome."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.actions import Action


@dataclass(frozen=True)
class LiarsDiceAction(Action):
    """Base class for Liar's Dice moves."""


@dataclass(frozen=True)
class Bid(LiarsDiceAction):
    """Claim that at least ``quantity`` dice across both hands show ``face``."""

    quantity: int
    face: int

    def __post_init__(self) -> None:
        if type(self.quantity) is not int or self.quantity < 1:
            raise ValueError("quantity must be a positive integer")
        if type(self.face) is not int or self.face < 1:
            raise ValueError("face must be a positive integer")

    def outranks(self, other: "Bid") -> bool:
        """Bids strictly rise: more dice, or as many dice of a higher face."""

        return (self.quantity, self.face) > (other.quantity, other.face)


@dataclass(frozen=True)
class Call(LiarsDiceAction):
    """Challenge the standing bid: both hands are revealed."""


@dataclass(frozen=True)
class Roll:
    """A chance outcome: both hands for a new round.

    Not an action — no seat chooses it, and it is never accepted from a seat. It
    is private: each seat may see only its own hand (see the serializer).
    """

    dice: tuple[tuple[int, ...], tuple[int, ...]]


__all__: Sequence[str] = ["Bid", "Call", "LiarsDiceAction", "Roll"]
