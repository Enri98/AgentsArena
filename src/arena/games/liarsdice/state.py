"""Immutable Liar's Dice state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.types import Seat
from arena.games.liarsdice.actions import Bid

VALID_SEATS = (0, 1)
MIN_FACES = 2
MAX_FACES = 9
#: The config's bound. load_state must refuse more: legal_actions enumerates
#: every bid up to the dice in play, so a forged count of 10**6 would hang it.
MAX_DICE_PER_SEAT = 6

Hands = tuple[tuple[int, ...], tuple[int, ...]]


@dataclass(frozen=True)
class Showdown:
    """What a call revealed. Public: once called, both hands are on the table."""

    caller: Seat
    bid: Bid
    dice: Hands
    count: int
    loser: Seat

    def __post_init__(self) -> None:
        if self.caller not in VALID_SEATS or self.loser not in VALID_SEATS:
            raise ValueError("caller and loser are seats")
        if len(self.dice) != 2 or not all(isinstance(hand, tuple) for hand in self.dice):
            raise ValueError("a showdown reveals one hand per seat")
        actual = sum(die == self.bid.face for hand in self.dice for die in hand)
        if self.count != actual:
            raise ValueError("a showdown's count must match the revealed dice")
        holds = actual >= self.bid.quantity
        # The caller loses when the bid held; the bidder (the other seat) otherwise.
        if self.loser != (self.caller if holds else 1 - self.caller):
            raise ValueError("a showdown's loser must follow from the bid and the dice")


@dataclass(frozen=True)
class LiarsDiceState:
    """Minimal immutable state for a Liar's Dice position.

    ``dice`` is ``None`` while a roll is pending — a chance node at the start of
    every round. ``dice_counts`` is public; the dice themselves are private to
    their seat until a showdown. ``bids`` is the current round's history, oldest
    first; the last one stands.
    """

    dice: Hands | None
    dice_counts: tuple[int, int]
    bids: tuple[Bid, ...]
    current_seat: Seat
    round_number: int
    faces: int
    last_showdown: Showdown | None = None

    def __post_init__(self) -> None:
        if type(self.faces) is not int or not MIN_FACES <= self.faces <= MAX_FACES:
            raise ValueError(f"faces must be between {MIN_FACES} and {MAX_FACES}")
        if type(self.round_number) is not int or self.round_number < 0:
            raise ValueError("round_number must be a non-negative integer")
        if self.dice is not None and self.round_number < 1:
            raise ValueError("dice are only dealt from round 1 on")
        if type(self.current_seat) is not int or self.current_seat not in VALID_SEATS:
            raise ValueError("current_seat must be 0 or 1")
        if len(self.dice_counts) != 2 or any(
            type(c) is not int or not 0 <= c <= MAX_DICE_PER_SEAT for c in self.dice_counts
        ):
            raise ValueError(
                f"dice_counts must be two integers between 0 and {MAX_DICE_PER_SEAT}"
            )
        if self.dice_counts == (0, 0):
            raise ValueError("a match always has a seat with dice left")
        finished = 0 in self.dice_counts
        if finished and self.current_seat != self.dice_counts.index(
            max(self.dice_counts)
        ):
            raise ValueError("a finished match leaves the winner as current_seat")
        if (finished or self.dice is None) and self.bids:
            raise ValueError("bids are only made once the round's dice are dealt")
        if finished and self.dice is not None:
            raise ValueError("no dice are dealt once the match is over")
        if self.round_number == 0 and self.last_showdown is not None:
            raise ValueError("no showdown can precede the first round")
        if self.last_showdown is not None:
            showdown = self.last_showdown
            if showdown.bid.face > self.faces or any(
                not 1 <= len(hand) <= MAX_DICE_PER_SEAT
                or any(type(d) is not int or not 1 <= d <= self.faces for d in hand)
                for hand in showdown.dice
            ):
                raise ValueError("a showdown reveals hands of this game's dice")
        if self.dice is not None:
            if len(self.dice) != 2:
                raise ValueError("dice must hold one hand per seat")
            for hand, count in zip(self.dice, self.dice_counts):
                if len(hand) != count:
                    raise ValueError("each hand must hold exactly dice_counts dice")
                if not isinstance(hand, tuple) or any(
                    type(d) is not int or not 1 <= d <= self.faces for d in hand
                ):
                    raise ValueError("every hand is a tuple of faces in 1..faces")
        total = sum(self.dice_counts)
        for index, bid in enumerate(self.bids):
            if bid.quantity > total or bid.face > self.faces:
                raise ValueError("a bid cannot exceed the dice in play or the die's faces")
            if index and not bid.outranks(self.bids[index - 1]):
                raise ValueError("bids within a round strictly rise")

    @property
    def standing_bid(self) -> Bid | None:
        return self.bids[-1] if self.bids else None


__all__: Sequence[str] = ["Hands", "LiarsDiceState", "Showdown", "VALID_SEATS"]
