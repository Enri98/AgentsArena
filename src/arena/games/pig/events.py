"""Pig domain events emitted by successful transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.events import DomainEvent
from arena.core.types import Seat


@dataclass(frozen=True)
class PigRollChosen(DomainEvent):
    """A seat chose to roll; the die is in the air (a chance node follows)."""

    seat: Seat


@dataclass(frozen=True)
class PigDieRolled(DomainEvent):
    """The die landed. Carried on the chance turn — a client cannot recompute it."""

    seat: Seat
    face: int
    busted: bool
    turn_total: int


@dataclass(frozen=True)
class PigHeld(DomainEvent):
    """A seat held, banking its turn total."""

    seat: Seat
    banked: int
    score: int


@dataclass(frozen=True)
class PigMatchWon(DomainEvent):
    """The match ended with a winner."""

    winner_seat: Seat


__all__: Sequence[str] = ["PigDieRolled", "PigHeld", "PigMatchWon", "PigRollChosen"]
