"""Nim rules engine."""

from __future__ import annotations

from typing import Sequence

from arena.core.actions import Action
from arena.core.events import DomainEvent
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import RuleResult, Win
from arena.core.rules_engine import TransitionResult
from arena.core.types import Seat
from arena.games.nim.actions import TakeObjects
from arena.games.nim.config import NimConfig
from arena.games.nim.events import NimMatchWon, NimObjectsTaken
from arena.games.nim.observation import NimObservation
from arena.games.nim.state import NimState


class NimRulesEngine:
    """Rules engine for normal-play Nim (last to take wins)."""

    def __init__(self, config: NimConfig | None = None) -> None:
        self._config = config or NimConfig()

    def initial_state(self, config: NimConfig) -> NimState:
        self._config = config
        piles = tuple(config.max_pile_size for _ in range(config.num_piles))
        return NimState(piles=piles, current_seat=0)

    def current_seat(self, state: NimState) -> Seat:
        return state.current_seat

    def legal_actions(self, state: NimState, seat: Seat) -> tuple[TakeObjects, ...]:
        if self.is_terminal(state) or seat != self.current_seat(state):
            return ()

        actions: list[TakeObjects] = []
        for pile_index, pile_size in enumerate(state.piles):
            for count in range(1, pile_size + 1):
                actions.append(TakeObjects(pile_index=pile_index, count=count))
        return tuple(actions)

    def validate_action(self, state: NimState, seat: Seat, action: Action) -> None:
        if self.is_terminal(state):
            raise GameFinished("Nim is already finished.")

        if seat != self.current_seat(state):
            raise WrongPlayer(
                "The provided seat is not active.",
                details={"seat": seat, "current_seat": self.current_seat(state)},
            )

        if not isinstance(action, TakeObjects):
            raise IllegalAction(
                "Nim requires TakeObjects actions.",
                details={"action_type": type(action).__name__},
            )

        if action.pile_index < 0 or action.pile_index >= len(state.piles):
            raise IllegalAction(
                "pile_index is out of range.",
                details={"pile_index": action.pile_index, "num_piles": len(state.piles)},
            )

        pile_size = state.piles[action.pile_index]
        if action.count < 1 or action.count > pile_size:
            raise IllegalAction(
                "count must be between 1 and the current pile size.",
                details={"count": action.count, "pile_size": pile_size},
            )

    def apply_action(
        self,
        state: NimState,
        seat: Seat,
        action: TakeObjects,
    ) -> TransitionResult[NimState, DomainEvent, RuleResult | None]:
        self.validate_action(state, seat, action)

        new_piles = tuple(
            size - action.count if i == action.pile_index else size
            for i, size in enumerate(state.piles)
        )

        events: list[DomainEvent] = [
            NimObjectsTaken(
                seat=seat,
                pile_index=action.pile_index,
                count=action.count,
                remaining=list(new_piles),
            )
        ]
        result: RuleResult | None = None

        if all(size == 0 for size in new_piles):
            # Normal play: the player who takes the last object wins.
            events.append(NimMatchWon(winner_seat=seat))
            result = Win(seat=seat)
            next_seat = seat
        else:
            next_seat = self._other_seat(seat)

        next_state = NimState(piles=new_piles, current_seat=next_seat)
        return TransitionResult(state=next_state, events=tuple(events), result=result)

    def is_terminal(self, state: NimState) -> bool:
        return self.result(state) is not None

    def result(self, state: NimState) -> RuleResult | None:
        if all(size == 0 for size in state.piles):
            # The player whose turn it would be is the loser; the other player won.
            # current_seat was set to the winner after the terminal move.
            # We store the winner as the seat that just moved (current_seat after move).
            # However, result() needs to reconstruct this from state alone.
            # Convention: when all piles are 0, the PREVIOUS player won.
            # We always set next_seat = seat (the mover) on terminal,
            # so current_seat IS the winner.
            return Win(seat=state.current_seat)
        return None

    def observation(self, state: NimState, seat: Seat) -> NimObservation:
        return NimObservation(
            seat=seat,
            piles=state.piles,
            current_seat=state.current_seat,
            legal_actions=self.legal_actions(state, seat),
        )

    def _other_seat(self, seat: Seat) -> Seat:
        return 1 if seat == 0 else 0


__all__: Sequence[str] = ["NimRulesEngine"]
