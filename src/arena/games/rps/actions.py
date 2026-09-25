"""Rock-Paper-Scissors actions: one throw per seat per round."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.actions import Action

ROCK = "rock"
PAPER = "paper"
SCISSORS = "scissors"
SHAPES = (ROCK, PAPER, SCISSORS)
#: shape -> the shape it beats
BEATS = {ROCK: SCISSORS, PAPER: ROCK, SCISSORS: PAPER}


@dataclass(frozen=True)
class Throw(Action):
    """One seat's throw for the round."""

    shape: str

    def __post_init__(self) -> None:
        if self.shape not in SHAPES:
            raise ValueError(f"shape must be one of {SHAPES}")


#: The scaffold's generic name for the game's action type.
RpsAction = Throw

__all__: Sequence[str] = ["BEATS", "PAPER", "ROCK", "RpsAction", "SCISSORS", "SHAPES", "Throw"]
