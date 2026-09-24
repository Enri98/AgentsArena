"""Immutable Rock-Paper-Scissors state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.types import Seat
from arena.games.rps.actions import BEATS, SHAPES
from arena.games.rps.config import MAX_ROUNDS_CAP, MAX_TARGET_WINS

VALID_SEATS = (0, 1)


def round_winner(throws: tuple[str, str]) -> Seat | None:
    """The seat whose throw beats the other's, or ``None`` for a tie."""

    if throws[0] == throws[1]:
        return None
    return 0 if BEATS[throws[0]] == throws[1] else 1


@dataclass(frozen=True)
class RoundResult:
    """What the last round revealed: both throws, and who won it."""

    throws: tuple[str, str]
    winner: Seat | None

    def __post_init__(self) -> None:
        if len(self.throws) != 2 or any(t not in SHAPES for t in self.throws):
            raise ValueError("a round reveals one throw per seat")
        if self.winner != round_winner(self.throws):
            raise ValueError("a round's winner must follow from the throws")


@dataclass(frozen=True)
class RpsState:
    """Minimal immutable state for a Rock-Paper-Scissors match.

    No seat's throw for the round in progress is ever part of state: a round is
    resolved from both throws at once (a joint turn, Phase 41), so there is
    nothing hidden to redact.
    """

    wins: tuple[int, int]
    rounds_played: int
    target_wins: int
    max_rounds: int
    last_round: RoundResult | None = None

    def __post_init__(self) -> None:
        if type(self.target_wins) is not int or not 1 <= self.target_wins <= MAX_TARGET_WINS:
            raise ValueError(f"target_wins must be an integer in 1..{MAX_TARGET_WINS}")
        if type(self.max_rounds) is not int or not 1 <= self.max_rounds <= MAX_ROUNDS_CAP:
            raise ValueError(f"max_rounds must be an integer in 1..{MAX_ROUNDS_CAP}")
        if len(self.wins) != 2 or any(type(w) is not int or w < 0 for w in self.wins):
            raise ValueError("wins must be two non-negative integers")
        if type(self.rounds_played) is not int or not 0 <= self.rounds_played <= self.max_rounds:
            raise ValueError("rounds_played must be in 0..max_rounds")
        if sum(self.wins) > self.rounds_played:
            raise ValueError("a seat cannot have won more rounds than were played")
        if any(w > self.target_wins for w in self.wins):
            raise ValueError("no seat can pass target_wins: the match ends on reaching it")
        if all(w == self.target_wins for w in self.wins):
            raise ValueError("only one seat can reach target_wins")
        if (self.rounds_played == 0) != (self.last_round is None):
            raise ValueError("last_round is present exactly when a round has been played")


__all__: Sequence[str] = ["RoundResult", "RpsState", "VALID_SEATS", "round_winner"]
