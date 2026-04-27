"""Tic-Tac-Toe domain events emitted by successful transitions."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.events import DomainEvent
from arena.core.types import Seat


@dataclass(frozen=True)
class MarkPlaced(DomainEvent):
    """A mark was placed into a specific cell."""

    seat: Seat
    row: int
    column: int


@dataclass(frozen=True)
class WinnerDetected(DomainEvent):
    """A winning seat was detected after a move."""

    winning_seat: Seat


@dataclass(frozen=True)
class GameDrawn(DomainEvent):
    """The board filled without producing a winner."""


__all__ = ["GameDrawn", "MarkPlaced", "WinnerDetected"]
