"""Validated configuration for the Nim game."""

from __future__ import annotations

from typing import Sequence

from pydantic import Field

from arena.core.config import BaseGameConfig


class NimConfig(BaseGameConfig):
    """Boundary-facing configuration for Nim.

    num_piles: number of piles (>=1).
    max_pile_size: initial size of every pile (>=1).
    """

    num_piles: int = Field(default=3, ge=1)
    max_pile_size: int = Field(default=7, ge=1)


__all__: Sequence[str] = ["NimConfig"]
