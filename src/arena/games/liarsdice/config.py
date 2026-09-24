"""Validated configuration for Liar's Dice."""

from __future__ import annotations

from typing import Sequence

from pydantic import Field

from arena.core.config import BaseGameConfig


class LiarsDiceConfig(BaseGameConfig):
    """Boundary-facing configuration for two-seat Liar's Dice.

    dice_per_seat: dice each seat starts with; losing a showdown costs one.
    faces: faces on each die.

    Deliberately no seed. Config is sent to both seats and embedded in every
    snapshot, so a seed here would let either seat reroll the opponent's hand.
    The match owns the generator (``arena.core.chance``).
    """

    dice_per_seat: int = Field(default=3, ge=1, le=6)
    faces: int = Field(default=6, ge=2, le=9)


__all__: Sequence[str] = ["LiarsDiceConfig"]
