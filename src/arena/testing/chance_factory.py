"""A minimal game with chance nodes, for exercising the Phase 37 contract.

The coin game opens at a chance node (an opening flip) and returns to one after
every move, so a short match exercises both places chance can occur: before any
seat acts, and in the same step as an action.

It is deliberately generic-test material, not a playable game — the exemplar
stochastic game is Pig (``arena.games.pig``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from arena.core.actions import Action
from arena.core.chance import ChanceRng
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
from arena.core.exceptions import (
    ChanceResolutionError,
    GameFinished,
    IllegalAction,
    WrongPlayer,
)
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import Draw
from arena.core.rules_engine import TransitionResult
from arena.core.serializer import JSONMapping
from arena.core.types import Seat


class CoinGameConfig(BaseGameConfig):
    max_turns: int = 4


@dataclass(frozen=True)
class CoinMove(Action):
    """The only move: pass the turn, which triggers the next flip."""


@dataclass(frozen=True)
class CoinOutcome:
    """A chance outcome: which face the coin landed on."""

    face: int


@dataclass(frozen=True)
class CoinObservation(Observation):
    flips: tuple[int, ...]


@dataclass(frozen=True)
class CoinState:
    turn: int
    max_turns: int
    flip_pending: bool
    flips: tuple[int, ...] = ()


@dataclass(frozen=True)
class CoinFlipped(DomainEvent):
    face: int


@dataclass(frozen=True)
class CoinMoved(DomainEvent):
    seat: Seat


class CoinRulesEngine:
    def initial_state(self, config: CoinGameConfig) -> CoinState:
        return CoinState(turn=0, max_turns=config.max_turns, flip_pending=True)

    def current_seat(self, state: CoinState) -> Seat:
        return state.turn % 2

    def legal_actions(self, state: CoinState, seat: Seat) -> tuple[CoinMove, ...]:
        if self.is_terminal(state) or state.flip_pending or seat != self.current_seat(state):
            return ()
        return (CoinMove(),)

    def validate_action(self, state: CoinState, seat: Seat, action: CoinMove) -> None:
        if self.is_terminal(state):
            raise GameFinished("The coin game is finished.")
        if state.flip_pending:
            raise IllegalAction("A flip is pending; no seat can move.")
        if seat != self.current_seat(state):
            raise WrongPlayer("Not this seat's turn.", details={"seat": seat})
        if not isinstance(action, CoinMove):
            raise IllegalAction("Unknown coin-game action.")

    def apply_action(
        self, state: CoinState, seat: Seat, action: CoinMove
    ) -> TransitionResult[CoinState, CoinMoved, Draw | None]:
        self.validate_action(state, seat, action)
        next_state = replace(state, turn=state.turn + 1, flip_pending=True)
        if self.is_terminal(next_state):
            next_state = replace(next_state, flip_pending=False)
        return TransitionResult(
            state=next_state,
            events=(CoinMoved(seat=seat),),
            result=self.result(next_state),
        )

    def is_chance_node(self, state: CoinState) -> bool:
        return state.flip_pending and not self.is_terminal(state)

    def sample_chance(self, state: CoinState, rng: ChanceRng) -> tuple[CoinOutcome, ChanceRng]:
        face, rng = rng.draw(2)
        return CoinOutcome(face=face), rng

    def apply_chance(
        self, state: CoinState, outcome: CoinOutcome
    ) -> TransitionResult[CoinState, CoinFlipped, None]:
        if not self.is_chance_node(state):
            raise ChanceResolutionError("No flip is pending.")
        if not isinstance(outcome, CoinOutcome) or outcome.face not in (0, 1):
            raise ChanceResolutionError(
                "A coin lands on 0 or 1.", details={"outcome": repr(outcome)}
            )
        return TransitionResult(
            state=replace(state, flip_pending=False, flips=state.flips + (outcome.face,)),
            events=(CoinFlipped(face=outcome.face),),
        )

    def is_terminal(self, state: CoinState) -> bool:
        return state.turn >= state.max_turns

    def result(self, state: CoinState) -> Draw | None:
        return Draw() if self.is_terminal(state) else None

    def observation(self, state: CoinState, seat: Seat) -> CoinObservation:
        return CoinObservation(seat=seat, flips=state.flips)


class CoinSerializer:
    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        assert isinstance(config, CoinGameConfig)
        return {"max_turns": config.max_turns}

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return CoinGameConfig(max_turns=payload["max_turns"])

    def dump_state(self, state: object) -> JSONMapping:
        assert isinstance(state, CoinState)
        return {
            "turn": state.turn,
            "max_turns": state.max_turns,
            "flip_pending": state.flip_pending,
            "flips": list(state.flips),
        }

    def load_state(self, payload: JSONMapping) -> object:
        return CoinState(
            turn=payload["turn"],
            max_turns=payload["max_turns"],
            flip_pending=payload["flip_pending"],
            flips=tuple(payload["flips"]),
        )

    def dump_action(self, action: object) -> JSONMapping:
        assert isinstance(action, CoinMove)
        return {"type": "move"}

    def load_action(self, payload: JSONMapping) -> object:
        return CoinMove()

    def dump_observation(self, observation: object) -> JSONMapping:
        assert isinstance(observation, CoinObservation)
        return {"seat": observation.seat, "flips": list(observation.flips)}

    def load_observation(self, payload: JSONMapping) -> object:
        return CoinObservation(seat=payload["seat"], flips=tuple(payload["flips"]))

    def dump_chance_outcome(self, outcome: object) -> JSONMapping:
        assert isinstance(outcome, CoinOutcome)
        return {"face": outcome.face}

    def load_chance_outcome(self, payload: JSONMapping) -> object:
        return CoinOutcome(face=payload["face"])


def build_coin_game_definition() -> GameDefinition[
    CoinGameConfig, CoinState, CoinMove, CoinObservation, Draw
]:
    return GameDefinition(
        game_id="coin-game",
        display_name="Coin Game",
        config_type=CoinGameConfig,
        state_type=CoinState,
        action_type=CoinMove,
        observation_type=CoinObservation,
        rules_engine=CoinRulesEngine(),
        serializer=CoinSerializer(),
        result_type=Draw,
        has_chance_nodes=True,
    )


__all__ = [
    "CoinFlipped",
    "CoinGameConfig",
    "CoinMove",
    "CoinOutcome",
    "CoinState",
    "build_coin_game_definition",
]
