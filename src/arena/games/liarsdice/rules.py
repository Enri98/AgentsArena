"""Two-seat Liar's Dice — the Phase 39 exemplar of hidden information plus chance.

Each round both hands are rolled at a chance node; each seat sees only its own.
Seats alternate bids, each claiming more dice showing some face across *both*
hands than the last. Instead of bidding, a seat may call. Both hands are then
revealed, and the bid holds if enough dice show its face. If it holds the
caller loses a die, otherwise the bidder does. The loser opens the next round,
which re-rolls. A seat with no dice left has lost the match.

No wild ones, no palifico, no spot-on calls (out of scope in the plan).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from arena.core.actions import Action
from arena.core.chance import ChanceRng
from arena.core.events import DomainEvent
from arena.core.exceptions import (
    ChanceResolutionError,
    GameFinished,
    IllegalAction,
    WrongPlayer,
)
from arena.core.results import RuleResult, Win
from arena.core.rules_engine import TransitionResult
from arena.core.types import Seat
from arena.games.liarsdice.actions import Bid, Call, LiarsDiceAction, Roll
from arena.games.liarsdice.config import LiarsDiceConfig
from arena.games.liarsdice.events import (
    BidCalled,
    BidMade,
    DiceDealt,
    DieLost,
    LiarsDiceMatchWon,
    RoundRolled,
)
from arena.games.liarsdice.observation import LiarsDiceObservation, LiarsDicePublicView
from arena.games.liarsdice.state import LiarsDiceState, Showdown


class LiarsDiceRulesEngine:
    """Rules engine for two-seat Liar's Dice."""

    def initial_state(self, config: LiarsDiceConfig) -> LiarsDiceState:
        return LiarsDiceState(
            dice=None,
            dice_counts=(config.dice_per_seat, config.dice_per_seat),
            bids=(),
            current_seat=0,
            round_number=0,
            faces=config.faces,
        )

    def current_seat(self, state: LiarsDiceState) -> Seat:
        return state.current_seat

    def legal_actions(self, state: LiarsDiceState, seat: Seat) -> tuple[LiarsDiceAction, ...]:
        if self.is_terminal(state) or self.is_chance_node(state) or seat != state.current_seat:
            return ()
        total = sum(state.dice_counts)
        standing = state.standing_bid
        bids = tuple(
            Bid(quantity=q, face=f)
            for q in range(1, total + 1)
            for f in range(1, state.faces + 1)
            if standing is None or Bid(quantity=q, face=f).outranks(standing)
        )
        # Call first: it is the move that ends a round, so a first-legal-action
        # playout (the shared chance contract) progresses instead of bidding up.
        return ((Call(),) if standing is not None else ()) + bids

    def validate_action(self, state: LiarsDiceState, seat: Seat, action: Action) -> None:
        if self.is_terminal(state):
            raise GameFinished("Liar's Dice is already finished.")
        if self.is_chance_node(state):
            raise IllegalAction("The dice are being rolled; no seat can act.")
        if seat != state.current_seat:
            raise WrongPlayer(
                "The provided seat is not active.",
                details={"seat": seat, "current_seat": state.current_seat},
            )
        if isinstance(action, Call):
            if state.standing_bid is None:
                raise IllegalAction("There is no bid to call yet; open with a bid.")
            return
        if not isinstance(action, Bid):
            raise IllegalAction(
                "Liar's Dice takes Bid or Call.",
                details={"action_type": type(action).__name__},
            )
        total = sum(state.dice_counts)
        if not 1 <= action.quantity <= total:
            raise IllegalAction(
                f"A bid's quantity is between 1 and the {total} dice in play.",
                details={"quantity": action.quantity},
            )
        if not 1 <= action.face <= state.faces:
            raise IllegalAction(
                f"A die face is between 1 and {state.faces}.", details={"face": action.face}
            )
        standing = state.standing_bid
        if standing is not None and not action.outranks(standing):
            raise IllegalAction(
                "A bid must raise the standing bid: more dice, or as many of a higher face.",
                details={
                    "standing": [standing.quantity, standing.face],
                    "bid": [action.quantity, action.face],
                },
            )

    def apply_action(
        self, state: LiarsDiceState, seat: Seat, action: LiarsDiceAction
    ) -> TransitionResult[LiarsDiceState, DomainEvent, RuleResult | None]:
        self.validate_action(state, seat, action)
        other = _other(seat)

        if isinstance(action, Bid):
            return TransitionResult(
                state=replace(state, bids=state.bids + (action,), current_seat=other),
                events=(BidMade(seat=seat, quantity=action.quantity, face=action.face),),
            )

        bid = state.standing_bid
        assert bid is not None and state.dice is not None
        count = sum(die == bid.face for hand in state.dice for die in hand)
        # The standing bid was made by the other seat (seats alternate).
        loser = seat if count >= bid.quantity else other
        counts = tuple(c - 1 if s == loser else c for s, c in enumerate(state.dice_counts))
        counts = (counts[0], counts[1])
        events: list[DomainEvent] = [
            BidCalled(
                seat=seat,
                dice=[list(hand) for hand in state.dice],
                quantity=bid.quantity,
                face=bid.face,
                count=count,
                loser=loser,
            ),
            DieLost(seat=loser, remaining=counts[loser]),
        ]
        # The loser opens the next round; at the end, the winner is shown to
        # hold the table rather than an eliminated seat.
        opener = loser if counts[loser] > 0 else _other(loser)
        next_state = LiarsDiceState(
            dice=None,  # a new roll is pending, unless the match is over
            dice_counts=counts,
            bids=(),
            current_seat=opener,
            round_number=state.round_number,
            faces=state.faces,
            last_showdown=Showdown(
                caller=seat, bid=bid, dice=state.dice, count=count, loser=loser
            ),
        )
        result = self.result(next_state)
        if result is not None:
            events.append(LiarsDiceMatchWon(winner_seat=_other(loser)))
        return TransitionResult(state=next_state, events=tuple(events), result=result)

    # -- chance hooks (arena.core.chance) -----------------------------------

    def is_chance_node(self, state: LiarsDiceState) -> bool:
        return state.dice is None and not self.is_terminal(state)

    def sample_chance(self, state: LiarsDiceState, rng: ChanceRng) -> tuple[Roll, ChanceRng]:
        first, rng = rng.draw_many(state.faces, state.dice_counts[0])
        second, rng = rng.draw_many(state.faces, state.dice_counts[1])
        return (
            Roll(dice=(tuple(d + 1 for d in first), tuple(d + 1 for d in second))),
            rng,
        )

    def apply_chance(
        self, state: LiarsDiceState, outcome: Roll
    ) -> TransitionResult[LiarsDiceState, DomainEvent, None]:
        if not self.is_chance_node(state):
            raise ChanceResolutionError("No roll is pending.")
        hands = getattr(outcome, "dice", None)
        if (
            not isinstance(outcome, Roll)
            or not isinstance(hands, tuple)
            or len(hands) != 2
            or not all(isinstance(hand, tuple) for hand in hands)
        ):
            raise ChanceResolutionError("A roll deals one tuple of dice per seat.")
        for hand, count in zip(hands, state.dice_counts):
            if len(hand) != count or any(
                type(d) is not int or not 1 <= d <= state.faces for d in hand
            ):
                raise ChanceResolutionError(
                    "Each hand must hold that seat's dice count, each die a valid face."
                )
        round_number = state.round_number + 1
        return TransitionResult(
            state=replace(state, dice=outcome.dice, bids=(), round_number=round_number),
            events=(
                RoundRolled(round_number=round_number, dice_counts=list(state.dice_counts)),
                DiceDealt(seat=0, dice=list(outcome.dice[0])),
                DiceDealt(seat=1, dice=list(outcome.dice[1])),
            ),
        )

    # -- terminal / views ------------------------------------------------------

    def is_terminal(self, state: LiarsDiceState) -> bool:
        return self.result(state) is not None

    def result(self, state: LiarsDiceState) -> RuleResult | None:
        for seat, count in enumerate(state.dice_counts):
            if count == 0:
                return Win(seat=_other(seat))
        return None

    def observation(self, state: LiarsDiceState, seat: Seat) -> LiarsDiceObservation:
        if type(seat) is not int or seat not in (0, 1):
            # dice[-1] would be the other seat's hand.
            raise ValueError(f"An observation is for seat 0 or 1, not {seat!r}.")
        return LiarsDiceObservation(
            seat=seat,
            my_dice=state.dice[seat] if state.dice is not None else (),
            dice_counts=state.dice_counts,
            bids=state.bids,
            current_seat=state.current_seat,
            round_number=state.round_number,
            faces=state.faces,
            last_showdown=state.last_showdown,
            legal_actions=self.legal_actions(state, seat),
        )

    def public_state(self, state: LiarsDiceState) -> LiarsDicePublicView:
        return LiarsDicePublicView(
            dice_counts=state.dice_counts,
            bids=state.bids,
            current_seat=state.current_seat,
            round_number=state.round_number,
            faces=state.faces,
            last_showdown=state.last_showdown,
            roll_pending=self.is_chance_node(state),
        )


def _other(seat: Seat) -> Seat:
    return 1 if seat == 0 else 0


__all__: Sequence[str] = ["LiarsDiceRulesEngine"]
