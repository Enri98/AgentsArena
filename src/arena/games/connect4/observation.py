"""Player-facing Connect 4 observation models."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.observations import Observation
from arena.core.types import Seat
from arena.games.connect4.actions import DropDisc
from arena.games.connect4.state import Connect4Board


@dataclass(frozen=True)
class Connect4Observation(Observation):
    """Public Connect 4 observation for a seat."""

    board: Connect4Board
    current_seat: Seat
    legal_actions: tuple[DropDisc, ...]


__all__ = ["Connect4Observation"]
