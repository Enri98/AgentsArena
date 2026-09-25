"""Validated configuration for Rock-Paper-Scissors."""

from __future__ import annotations

from typing import Sequence

from pydantic import Field

from arena.core.config import BaseGameConfig

DEFAULT_TARGET_WINS = 3
DEFAULT_MAX_ROUNDS = 20
MAX_TARGET_WINS = 10
MAX_ROUNDS_CAP = 100


class RpsConfig(BaseGameConfig):
    """Boundary-facing configuration for Rock-Paper-Scissors.

    target_wins: rounds a seat must win to take the match (1-10).
    max_rounds: rounds played at most (1-100). Two seats that keep drawing (or
    two agents that keep throwing the same shape) cannot run a match forever;
    at the cap the seat with more wins takes it, and equal wins is a draw.
    """

    target_wins: int = Field(default=DEFAULT_TARGET_WINS, ge=1, le=MAX_TARGET_WINS)
    max_rounds: int = Field(default=DEFAULT_MAX_ROUNDS, ge=1, le=MAX_ROUNDS_CAP)


__all__: Sequence[str] = ["RpsConfig"]
