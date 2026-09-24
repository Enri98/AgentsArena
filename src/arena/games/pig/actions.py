"""Pig action model and chance outcome."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.actions import Action

ROLL = "roll"
HOLD = "hold"
PIG_CHOICES = (ROLL, HOLD)

#: Faces on the die. Rolling a 1 busts the turn.
DIE_FACES = 6
BUST_FACE = 1


@dataclass(frozen=True)
class PigMove(Action):
    """A seat's decision: ``"roll"`` the die again, or ``"hold"`` and bank."""

    choice: str

    def __post_init__(self) -> None:
        if self.choice not in PIG_CHOICES:
            raise ValueError(f"choice must be one of {PIG_CHOICES}, got {self.choice!r}")


@dataclass(frozen=True)
class DieRoll:
    """A chance outcome: the face the die landed on.

    Not an ``Action``: no seat chooses it, and it is never accepted from a seat.
    """

    face: int

    def __post_init__(self) -> None:
        if type(self.face) is not int:
            raise ValueError("face must be an integer")


__all__: Sequence[str] = [
    "BUST_FACE",
    "DIE_FACES",
    "DieRoll",
    "HOLD",
    "PIG_CHOICES",
    "PigMove",
    "ROLL",
]
