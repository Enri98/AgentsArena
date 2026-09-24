"""Validated configuration for the Nim game."""

from __future__ import annotations

from typing import Sequence

from pydantic import Field

from arena.core.config import BaseGameConfig


class NimConfig(BaseGameConfig):
    """Boundary-facing configuration for Nim.

    num_piles: number of piles (1-20).
    max_pile_size: initial size of every pile (1-100).

    Bounded: every snapshot carries every pile, and a match lasts up to
    ``num_piles * max_pile_size`` turns, so unbounded values let one match's
    transcript grow as large as a client liked.
    """

    num_piles: int = Field(default=3, ge=1, le=20)
    max_pile_size: int = Field(default=7, ge=1, le=100)


__all__: Sequence[str] = ["NimConfig"]
