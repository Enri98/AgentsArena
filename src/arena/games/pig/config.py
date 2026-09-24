"""Validated configuration for Pig."""

from __future__ import annotations

from typing import Sequence

from pydantic import Field

from arena.core.config import BaseGameConfig

#: Default target. The classic game plays to 100; 50 keeps agent matches short.
DEFAULT_TARGET_SCORE = 50


class PigConfig(BaseGameConfig):
    """Boundary-facing configuration for Pig.

    target_score: points a seat must bank to win.

    There is deliberately no seed here: config is sent to both seats and embedded
    in every snapshot, so a seed in it would let either seat predict the dice.
    The match owns the generator (see ``arena.core.chance``).
    """

    target_score: int = Field(default=DEFAULT_TARGET_SCORE, ge=1, le=1000)


__all__: Sequence[str] = ["DEFAULT_TARGET_SCORE", "PigConfig"]
