"""Factory helpers for generic game-contract tests."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import Draw
from arena.core.rules_engine import TransitionResult
from arena.core.serializer import JSONMapping
from arena.core.types import Seat


class FakeGameConfig(BaseGameConfig):
    """Validated config for the generic fake game used by the test harness."""

    max_turns: int = 2


@dataclass(frozen=True)
class FakeAction(Action):
    """Minimal action for the generic fake game."""

    amount: int


@dataclass(frozen=True)
class FakeObservation(Observation):
    """Minimal observation for the generic fake game."""

    turn: int
    remaining_turns: int


@dataclass(frozen=True)
class FakeState:
    """Minimal immutable state for the generic fake game."""

    turn: int
    max_turns: int


@dataclass(frozen=True)
class FakeMoveApplied(DomainEvent):
    """Event emitted for each successful fake-game move."""

    seat: Seat
    amount: int


class FakeRulesEngine:
    """Tiny rules engine used to prove the shared test harness shape."""

    def initial_state(self, config: FakeGameConfig) -> FakeState:
        return FakeState(turn=0, max_turns=config.max_turns)

    def current_seat(self, state: FakeState) -> Seat:
        return state.turn % 2

    def legal_actions(self, state: FakeState, seat: Seat) -> tuple[FakeAction, ...]:
        if self.is_terminal(state):
            return ()

        if seat != self.current_seat(state):
            return ()

        return (FakeAction(amount=1),)

    def validate_action(self, state: FakeState, seat: Seat, action: FakeAction) -> None:
        if self.is_terminal(state):
            raise GameFinished("The fake game is already finished.")

        if seat != self.current_seat(state):
            raise WrongPlayer("The provided seat is not active.", details={"seat": seat})

        if action not in self.legal_actions(state, seat):
            raise IllegalAction(
                "The fake action is not legal for this state.",
                details={"action": action.action_type},
            )

    def apply_action(
        self,
        state: FakeState,
        seat: Seat,
        action: FakeAction,
    ) -> TransitionResult[FakeState, FakeMoveApplied, Draw | None]:
        self.validate_action(state, seat, action)

        next_state = FakeState(turn=state.turn + action.amount, max_turns=state.max_turns)
        result = Draw() if self.is_terminal(next_state) else None

        return TransitionResult(
            state=next_state,
            events=(FakeMoveApplied(seat=seat, amount=action.amount),),
            result=result,
        )

    def is_terminal(self, state: FakeState) -> bool:
        return state.turn >= state.max_turns

    def result(self, state: FakeState) -> Draw | None:
        return Draw() if self.is_terminal(state) else None

    def observation(self, state: FakeState, seat: Seat) -> FakeObservation:
        remaining_turns = max(state.max_turns - state.turn, 0)
        return FakeObservation(seat=seat, turn=state.turn, remaining_turns=remaining_turns)


class FakeSerializer:
    """Serializer for the generic fake game used in contract tests."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        fake_config = _expect_fake_config(config)
        return {"max_turns": fake_config.max_turns}

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return FakeGameConfig(max_turns=payload["max_turns"])

    def dump_state(self, state: object) -> JSONMapping:
        fake_state = _expect_fake_state(state)
        return {"turn": fake_state.turn, "max_turns": fake_state.max_turns}

    def load_state(self, payload: JSONMapping) -> object:
        return FakeState(turn=payload["turn"], max_turns=payload["max_turns"])

    def dump_action(self, action: object) -> JSONMapping:
        fake_action = _expect_fake_action(action)
        return {"amount": fake_action.amount}

    def load_action(self, payload: JSONMapping) -> object:
        return FakeAction(amount=payload["amount"])

    def dump_observation(self, observation: object) -> JSONMapping:
        fake_observation = _expect_fake_observation(observation)
        return {
            "seat": fake_observation.seat,
            "turn": fake_observation.turn,
            "remaining_turns": fake_observation.remaining_turns,
        }

    def load_observation(self, payload: JSONMapping) -> object:
        return FakeObservation(
            seat=payload["seat"],
            turn=payload["turn"],
            remaining_turns=payload["remaining_turns"],
        )


@dataclass(frozen=True)
class FakeGameBundle:
    """Coherent fake-game bundle for shared contract tests."""

    definition: GameDefinition[FakeGameConfig, FakeState, FakeAction, FakeObservation, Draw]
    config: FakeGameConfig
    initial_state: FakeState
    near_terminal_state: FakeState
    terminal_state: FakeState
    legal_action: FakeAction
    illegal_action: FakeAction


def build_fake_game_bundle() -> FakeGameBundle:
    """Build a minimal fake game bundle for the shared test harness."""

    config = FakeGameConfig(max_turns=2)
    rules_engine = FakeRulesEngine()
    serializer = FakeSerializer()
    definition = GameDefinition(
        game_id="fake-game",
        display_name="Fake Game",
        config_type=FakeGameConfig,
        state_type=FakeState,
        action_type=FakeAction,
        observation_type=FakeObservation,
        rules_engine=rules_engine,
        serializer=serializer,
        result_type=Draw,
    )

    return FakeGameBundle(
        definition=definition,
        config=config,
        initial_state=rules_engine.initial_state(config),
        near_terminal_state=FakeState(turn=1, max_turns=config.max_turns),
        terminal_state=FakeState(turn=config.max_turns, max_turns=config.max_turns),
        legal_action=FakeAction(amount=1),
        illegal_action=FakeAction(amount=2),
    )


def _expect_fake_config(config: BaseGameConfig) -> FakeGameConfig:
    if not isinstance(config, FakeGameConfig):
        raise TypeError(f"Expected FakeGameConfig, got {type(config).__name__}.")
    return config


def _expect_fake_state(state: object) -> FakeState:
    if not isinstance(state, FakeState):
        raise TypeError(f"Expected FakeState, got {type(state).__name__}.")
    return state


def _expect_fake_action(action: object) -> FakeAction:
    if not isinstance(action, FakeAction):
        raise TypeError(f"Expected FakeAction, got {type(action).__name__}.")
    return action


def _expect_fake_observation(observation: object) -> FakeObservation:
    if not isinstance(observation, FakeObservation):
        raise TypeError(f"Expected FakeObservation, got {type(observation).__name__}.")
    return observation
