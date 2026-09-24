"""Rock-Paper-Scissors domain events. All public: throws are revealed together."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.events import DomainEvent
from arena.core.types import Seat


@dataclass(frozen=True)
class RoundPlayed(DomainEvent):
    """Both throws of a round, revealed at once, and who won it (None: a tie)."""

    round_number: int
    throws: list[str]  # a list, not a tuple: event fields must dump as JSON arrays
    winner: Seat | None


@dataclass(frozen=True)
class RpsMatchDecided(DomainEvent):
    """The match ended: a seat reached target_wins, or max_rounds ran out."""

    winner: Seat | None


__all__: Sequence[str] = ["RoundPlayed", "RpsMatchDecided"]
