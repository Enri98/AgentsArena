"""Player-facing Tic-Tac-Toe observation models."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.observations import Observation
from arena.core.types import Seat
from arena.games.tictactoe.actions import PlaceMark
from arena.games.tictactoe.state import TicTacToeBoard


@dataclass(frozen=True)
class TicTacToeObservation(Observation):
    """Public Tic-Tac-Toe observation for a seat."""

    board: TicTacToeBoard
    current_seat: Seat
    legal_actions: tuple[PlaceMark, ...]


__all__ = ["TicTacToeObservation"]
