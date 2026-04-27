"""Validated configuration for the Tic-Tac-Toe game."""

from __future__ import annotations

from typing import Literal

from arena.core.config import BaseGameConfig


class TicTacToeConfig(BaseGameConfig):
    """Boundary-facing configuration for the standard 3x3 Tic-Tac-Toe board."""

    rows: Literal[3] = 3
    columns: Literal[3] = 3
    connect_length: Literal[3] = 3


__all__ = ["TicTacToeConfig"]
