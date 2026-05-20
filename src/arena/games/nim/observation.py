"""Player-facing Nim observation model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.observations import Observation
from arena.core.types import Seat
from arena.games.nim.actions import TakeObjects
from arena.games.nim.state import NimPiles


@dataclass(frozen=True)
class NimObservation(Observation):
    """Public Nim observation for a seat."""

    piles: NimPiles
    current_seat: Seat
    legal_actions: tuple[TakeObjects, ...]


__all__: Sequence[str] = ["NimObservation"]
