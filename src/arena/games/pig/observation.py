"""Player-facing Pig observation model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.observations import Observation
from arena.core.types import Seat
from arena.games.pig.actions import PigMove


@dataclass(frozen=True)
class PigObservation(Observation):
    """Public Pig observation for a seat. Pig has no hidden information."""

    scores: tuple[int, int]
    current_seat: Seat
    turn_total: int
    target_score: int
    legal_actions: tuple[PigMove, ...]


__all__: Sequence[str] = ["PigObservation"]
