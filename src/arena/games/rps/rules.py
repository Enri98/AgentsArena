"""Rock-Paper-Scissors rules engine: the Phase 41 exemplar simultaneous game.

Every round both seats throw at once, each without seeing the other's choice.
A round is one joint turn (``arena.core.simultaneous``): each throw is checked
with ``validate_action`` as it arrives, and ``apply_joint_action`` resolves the
round from both. No seat ever acts alone, so ``apply_action`` always refuses.

The first seat to win ``target_wins`` rounds takes the match. After
``max_rounds`` the seat with more wins takes it, and equal wins is a draw.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Sequence

from arena.core.actions import Action
from arena.core.events import DomainEvent
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Draw, RuleResult, Win
from arena.core.rules_engine import TransitionResult
from arena.core.types import Seat
from arena.games.rps.actions import SHAPES, Throw
from arena.games.rps.config import RpsConfig
from arena.games.rps.events import RoundPlayed, RpsMatchDecided
from arena.games.rps.observation import RpsObservation
from arena.games.rps.state import VALID_SEATS, RoundResult, RpsState, round_winner

_ALL_THROWS = tuple(Throw(shape=shape) for shape in SHAPES)


class RpsRulesEngine:
    """Rules engine for two-seat Rock-Paper-Scissors."""

    def initial_state(self, config: RpsConfig) -> RpsState:
        return RpsState(
            wins=(0, 0),
            rounds_played=0,
            target_wins=config.target_wins,
            max_rounds=config.max_rounds,
        )

    # -- seats -------------------------------------------------------------

    def current_seat(self, state: RpsState) -> Seat:
        # Both seats act every round; see acting_seats. Seat 0 by convention,
        # which also names the winner's seat at a finished state when it is 0.
        result = self.result(state)
        if isinstance(result, Win):
            return result.seat
        return 0

    def acting_seats(self, state: RpsState) -> tuple[Seat, ...]:
        return () if self.is_terminal(state) else VALID_SEATS

    # -- actions -----------------------------------------------------------

    def legal_actions(self, state: RpsState, seat: Seat) -> tuple[Throw, ...]:
        if self.is_terminal(state) or seat not in VALID_SEATS:
            return ()
        return _ALL_THROWS

    def validate_action(self, state: RpsState, seat: Seat, action: Action) -> None:
        if self.is_terminal(state):
            raise GameFinished("The match is already over.")
        if seat not in VALID_SEATS:
            raise WrongPlayer("Only seats 0 and 1 play.", details={"seat": seat})
        if not isinstance(action, Throw):
            raise IllegalAction(
                "Rock-Paper-Scissors takes Throw actions.",
                details={"action_type": type(action).__name__},
            )

    def apply_action(
        self, state: RpsState, seat: Seat, action: Action
    ) -> TransitionResult[RpsState, DomainEvent, RuleResult | None]:
        if self.is_terminal(state):
            raise GameFinished("The match is already over.")
        raise WrongPlayer(
            "Both seats throw at once: a round is resolved with apply_joint_action.",
            details={"seat": seat},
        )

    def apply_joint_action(
        self, state: RpsState, actions: Mapping[Seat, Action]
    ) -> TransitionResult[RpsState, DomainEvent, RuleResult | None]:
        if sorted(actions) != list(VALID_SEATS):
            raise WrongPlayer(
                "A round needs one throw from each seat.",
                details={"seats": sorted(actions)},
            )
        for seat in VALID_SEATS:
            self.validate_action(state, seat, actions[seat])
        throws = (actions[0].shape, actions[1].shape)  # type: ignore[attr-defined]
        winner = round_winner(throws)
        wins = list(state.wins)
        if winner is not None:
            wins[winner] += 1
        next_state = replace(
            state,
            wins=(wins[0], wins[1]),
            rounds_played=state.rounds_played + 1,
            last_round=RoundResult(throws=throws, winner=winner),
        )
        events: list[DomainEvent] = [
            RoundPlayed(
                round_number=next_state.rounds_played, throws=list(throws), winner=winner
            )
        ]
        result = self.result(next_state)
        if result is not None:
            events.append(
                RpsMatchDecided(winner=result.seat if isinstance(result, Win) else None)
            )
        return TransitionResult(state=next_state, events=tuple(events), result=result)

    # -- outcome -----------------------------------------------------------

    def is_terminal(self, state: RpsState) -> bool:
        return (
            max(state.wins) >= state.target_wins or state.rounds_played >= state.max_rounds
        )

    def result(self, state: RpsState) -> RuleResult | None:
        if not self.is_terminal(state):
            return None
        if state.wins[0] == state.wins[1]:
            return Draw()
        return Win(seat=0 if state.wins[0] > state.wins[1] else 1)

    def observation(self, state: RpsState, seat: Seat) -> RpsObservation:
        if seat not in VALID_SEATS:
            raise WrongPlayer("Only seats 0 and 1 play.", details={"seat": seat})
        return RpsObservation(
            seat=seat,
            wins=state.wins,
            rounds_played=state.rounds_played,
            target_wins=state.target_wins,
            max_rounds=state.max_rounds,
            last_round=state.last_round,
            legal_actions=self.legal_actions(state, seat),
        )


__all__: Sequence[str] = ["RpsRulesEngine"]
