"""Player-facing Rock-Paper-Scissors observation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.observations import Observation
from arena.core.types import Seat
from arena.games.rps.actions import Throw
from arena.games.rps.state import RoundResult


@dataclass(frozen=True)
class RpsObservation(Observation):
    """What a seat sees when choosing its throw: the score so far, never the
    opponent's pending throw (it does not exist yet anywhere a seat can see)."""

    seat: Seat
    wins: tuple[int, int]
    rounds_played: int
    target_wins: int
    max_rounds: int
    last_round: RoundResult | None
    legal_actions: tuple[Throw, ...]


__all__: Sequence[str] = ["RpsObservation"]
