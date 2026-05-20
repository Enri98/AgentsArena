"""Nim domain events emitted by successful transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.events import DomainEvent
from arena.core.types import Seat


@dataclass(frozen=True)
class NimObjectsTaken(DomainEvent):
    """Objects were taken from a pile."""

    seat: Seat
    pile_index: int
    count: int
    remaining: list[int]  # list for JSON-native serialization


@dataclass(frozen=True)
class NimMatchWon(DomainEvent):
    """The match ended with a winner."""

    winner_seat: Seat


__all__: Sequence[str] = ["NimMatchWon", "NimObjectsTaken"]
