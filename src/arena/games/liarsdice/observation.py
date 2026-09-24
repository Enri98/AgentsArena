"""Player-facing Liar's Dice observation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.observations import Observation
from arena.core.types import Seat
from arena.games.liarsdice.actions import Bid, LiarsDiceAction
from arena.games.liarsdice.state import Showdown


@dataclass(frozen=True)
class LiarsDiceObservation(Observation):
    """What one seat knows: its own dice, never the opponent's.

    ``my_dice`` is empty while a roll is pending. ``last_showdown`` is public:
    the hands a call revealed.
    """

    my_dice: tuple[int, ...]
    dice_counts: tuple[int, int]
    bids: tuple[Bid, ...]
    current_seat: Seat
    round_number: int
    faces: int
    last_showdown: Showdown | None
    legal_actions: tuple[LiarsDiceAction, ...]


@dataclass(frozen=True)
class LiarsDicePublicView:
    """The spectator's view: everything but the hidden dice."""

    dice_counts: tuple[int, int]
    bids: tuple[Bid, ...]
    current_seat: Seat
    round_number: int
    faces: int
    last_showdown: Showdown | None
    roll_pending: bool


__all__: Sequence[str] = ["LiarsDiceObservation", "LiarsDicePublicView"]
