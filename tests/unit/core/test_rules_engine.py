"""Tests for shared transition result primitives."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
from arena.core.observations import Observation
from arena.core.results import Draw
from arena.core.rules_engine import RulesEngine, TransitionResult


@dataclass(frozen=True)
class ExampleEvent(DomainEvent):
    column: int


@dataclass(frozen=True)
class ExampleAction(Action):
    column: int


@dataclass(frozen=True)
class ExampleObservation(Observation):
    visible_columns: tuple[int, ...]


@dataclass(frozen=True)
class ExampleState:
    turn: int


class ExampleConfig(BaseGameConfig):
    rows: int


class ExampleRulesEngine:
    def initial_state(self, config: BaseGameConfig) -> ExampleState:
        return ExampleState(turn=0)

    def current_seat(self, state: ExampleState) -> int:
        return state.turn % 2

    def legal_actions(self, state: ExampleState, seat: int) -> tuple[ExampleAction, ...]:
        return (ExampleAction(column=0),)

    def validate_action(self, state: ExampleState, seat: int, action: ExampleAction) -> None:
        return None

    def apply_action(
        self,
        state: ExampleState,
        seat: int,
        action: ExampleAction,
    ) -> TransitionResult[ExampleState, ExampleEvent, Draw]:
        return TransitionResult(
            state=ExampleState(turn=state.turn + 1),
            events=(ExampleEvent(column=action.column),),
            result=Draw(),
        )

    def is_terminal(self, state: ExampleState) -> bool:
        return False

    def result(self, state: ExampleState) -> Draw | None:
        return None

    def observation(self, state: ExampleState, seat: int) -> ExampleObservation:
        return ExampleObservation(seat=seat, visible_columns=(0,))


def test_transition_result_normalizes_events_to_a_tuple() -> None:
    result = TransitionResult(
        state={"board": "after"},
        events=[ExampleEvent(column=2)],
        result=None,
    )

    assert result.events == (ExampleEvent(column=2),)


def test_transition_result_stores_the_optional_rule_result_verbatim() -> None:
    result = TransitionResult(
        state={"board": "after"},
        events=(),
        result=Draw(),
    )

    assert result.result == Draw()


def test_transition_result_is_immutable() -> None:
    result = TransitionResult(state={"board": "after"})

    with pytest.raises(FrozenInstanceError):
        result.state = {"board": "mutated"}


def test_rules_engine_protocol_accepts_a_trivial_game_engine() -> None:
    engine = ExampleRulesEngine()

    assert isinstance(engine, RulesEngine)
    assert engine.initial_state(ExampleConfig(rows=6)) == ExampleState(turn=0)
