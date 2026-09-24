"""Pig rules engine — the Phase 37 exemplar stochastic game.

Each turn the active seat rolls a die until it either holds, banking the turn
total, or rolls a 1 and loses it. The first seat to bank ``target_score`` wins.

Every roll is a chance node: ``apply_action(roll)`` only records that the die is
in the air, and the outcome is resolved through ``sample_chance`` /
``apply_chance``. A turn always begins with a roll — holding on zero is illegal —
so two agents cannot stall a match by passing back and forth.
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
from arena.games.pig.actions import BUST_FACE, DIE_FACES, HOLD, ROLL, DieRoll, PigMove
from arena.games.pig.config import PigConfig
from arena.games.pig.events import PigDieRolled, PigHeld, PigMatchWon, PigRollChosen
from arena.games.pig.observation import PigObservation
from arena.games.pig.state import PigState


class PigRulesEngine:
    """Rules engine for two-seat Pig."""

    def initial_state(self, config: PigConfig) -> PigState:
        return PigState(
            scores=(0, 0),
            current_seat=0,
            turn_total=0,
            roll_pending=False,
            target_score=config.target_score,
        )

    def current_seat(self, state: PigState) -> Seat:
        return state.current_seat

    def legal_actions(self, state: PigState, seat: Seat) -> tuple[PigMove, ...]:
        if self.is_terminal(state) or state.roll_pending or seat != state.current_seat:
            return ()
        if state.turn_total == 0:
            return (PigMove(choice=ROLL),)
        return (PigMove(choice=ROLL), PigMove(choice=HOLD))

    def validate_action(self, state: PigState, seat: Seat, action: Action) -> None:
        if self.is_terminal(state):
            raise GameFinished("Pig is already finished.")

        if state.roll_pending:
            raise IllegalAction("The die is still in the air; no seat can act.")

        if seat != state.current_seat:
            raise WrongPlayer(
                "The provided seat is not active.",
                details={"seat": seat, "current_seat": state.current_seat},
            )

        if not isinstance(action, PigMove):
            raise IllegalAction(
                "Pig requires PigMove actions.",
                details={"action_type": type(action).__name__},
            )

        if action.choice == HOLD and state.turn_total == 0:
            raise IllegalAction(
                "A turn starts with a roll; there is nothing to hold yet.",
                details={"choice": action.choice, "turn_total": state.turn_total},
            )

    def apply_action(
        self,
        state: PigState,
        seat: Seat,
        action: PigMove,
    ) -> TransitionResult[PigState, DomainEvent, RuleResult | None]:
        self.validate_action(state, seat, action)

        if action.choice == ROLL:
            return TransitionResult(
                state=replace(state, roll_pending=True),
                events=(PigRollChosen(seat=seat),),
            )

        score = state.scores[seat] + state.turn_total
        scores = _with_score(state.scores, seat, score)
        events: list[DomainEvent] = [PigHeld(seat=seat, banked=state.turn_total, score=score)]

        if score >= state.target_score:
            # The winner stays current_seat, as Nim does; result() reads scores.
            next_state = replace(state, scores=scores, turn_total=0)
            events.append(PigMatchWon(winner_seat=seat))
        else:
            next_state = replace(
                state, scores=scores, turn_total=0, current_seat=_other_seat(seat)
            )

        return TransitionResult(
            state=next_state, events=tuple(events), result=self.result(next_state)
        )

    # -- chance hooks (arena.core.chance) -----------------------------------

    def is_chance_node(self, state: PigState) -> bool:
        return state.roll_pending and not self.is_terminal(state)

    def sample_chance(self, state: PigState, rng: ChanceRng) -> tuple[DieRoll, ChanceRng]:
        value, rng = rng.draw(DIE_FACES)
        return DieRoll(face=value + 1), rng

    def apply_chance(
        self, state: PigState, outcome: DieRoll
    ) -> TransitionResult[PigState, DomainEvent, None]:
        if not self.is_chance_node(state):
            raise ChanceResolutionError("No roll is pending.")
        if not isinstance(outcome, DieRoll) or not 1 <= outcome.face <= DIE_FACES:
            raise ChanceResolutionError(
                f"A die roll lands on 1-{DIE_FACES}.",
                details={"outcome": repr(outcome)},
            )

        seat = state.current_seat
        if outcome.face == BUST_FACE:
            next_state = replace(
                state, roll_pending=False, turn_total=0, current_seat=_other_seat(seat)
            )
            busted = True
        else:
            next_state = replace(
                state, roll_pending=False, turn_total=state.turn_total + outcome.face
            )
            busted = False

        return TransitionResult(
            state=next_state,
            events=(
                PigDieRolled(
                    seat=seat,
                    face=outcome.face,
                    busted=busted,
                    turn_total=next_state.turn_total,
                ),
            ),
        )

    # -- terminal -------------------------------------------------------------

    def is_terminal(self, state: PigState) -> bool:
        return self.result(state) is not None

    def result(self, state: PigState) -> RuleResult | None:
        for seat, score in enumerate(state.scores):
            if score >= state.target_score:
                return Win(seat=seat)
        return None

    def observation(self, state: PigState, seat: Seat) -> PigObservation:
        return PigObservation(
            seat=seat,
            scores=state.scores,
            current_seat=state.current_seat,
            turn_total=state.turn_total,
            target_score=state.target_score,
            legal_actions=self.legal_actions(state, seat),
        )


def _other_seat(seat: Seat) -> Seat:
    return 1 if seat == 0 else 0


def _with_score(scores: tuple[int, int], seat: Seat, score: int) -> tuple[int, int]:
    return (score, scores[1]) if seat == 0 else (scores[0], score)


__all__: Sequence[str] = ["PigRulesEngine"]
