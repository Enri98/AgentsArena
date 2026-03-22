"""Tests for the shared manual game registry."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.exceptions import DuplicateGameRegistration, UnknownGame
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.registry import GameRegistry
from arena.core.results import Draw
from arena.core.rules_engine import TransitionResult
from arena.core.serializer import JSONMapping


class ExampleConfig(BaseGameConfig):
    rows: int


@dataclass(frozen=True)
class ExampleAction(Action):
    column: int


@dataclass(frozen=True)
class ExampleObservation(Observation):
    visible_columns: tuple[int, ...]


@dataclass(frozen=True)
class ExampleState:
    turn: int


class ExampleSerializer:
    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        return {"rows": config.model_dump()["rows"]}

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return ExampleConfig(rows=payload["rows"])

    def dump_state(self, state: object) -> JSONMapping:
        return {"turn": getattr(state, "turn")}

    def load_state(self, payload: JSONMapping) -> object:
        return ExampleState(turn=payload["turn"])

    def dump_action(self, action: object) -> JSONMapping:
        return {"column": getattr(action, "column")}

    def load_action(self, payload: JSONMapping) -> object:
        return ExampleAction(column=payload["column"])

    def dump_observation(self, observation: object) -> JSONMapping:
        return {
            "seat": getattr(observation, "seat"),
            "visible_columns": list(getattr(observation, "visible_columns")),
        }

    def load_observation(self, payload: JSONMapping) -> object:
        return ExampleObservation(
            seat=payload["seat"],
            visible_columns=tuple(payload["visible_columns"]),
        )


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
    ) -> TransitionResult[ExampleState, object, Draw]:
        return TransitionResult(state=ExampleState(turn=state.turn + 1), result=Draw())

    def is_terminal(self, state: ExampleState) -> bool:
        return False

    def result(self, state: ExampleState) -> Draw | None:
        return None

    def observation(self, state: ExampleState, seat: int) -> ExampleObservation:
        return ExampleObservation(seat=seat, visible_columns=(0,))


def build_definition(game_id: str, display_name: str) -> GameDefinition:
    return GameDefinition(
        game_id=game_id,
        display_name=display_name,
        config_type=ExampleConfig,
        state_type=ExampleState,
        action_type=ExampleAction,
        observation_type=ExampleObservation,
        rules_engine=ExampleRulesEngine(),
        serializer=ExampleSerializer(),
        result_type=Draw,
    )


def test_registry_registers_and_resolves_a_game_definition() -> None:
    registry = GameRegistry()
    definition = build_definition(game_id="example", display_name="Example")

    registry.register(definition)

    assert registry.get("example") is definition


def test_registry_rejects_duplicate_registration() -> None:
    registry = GameRegistry()
    definition = build_definition(game_id="example", display_name="Example")

    registry.register(definition)

    with pytest.raises(DuplicateGameRegistration):
        registry.register(definition)


def test_registry_rejects_duplicate_game_ids_from_distinct_definitions() -> None:
    registry = GameRegistry()
    first = build_definition(game_id="example", display_name="Example")
    second = build_definition(game_id="example", display_name="Example v2")

    registry.register(first)

    with pytest.raises(DuplicateGameRegistration):
        registry.register(second)


def test_registry_lists_definitions_in_registration_order() -> None:
    registry = GameRegistry()
    first = build_definition(game_id="example-a", display_name="Example A")
    second = build_definition(game_id="example-b", display_name="Example B")

    registry.register(first)
    registry.register(second)

    assert registry.list() == (first, second)


def test_registry_raises_for_unknown_games() -> None:
    registry = GameRegistry()

    with pytest.raises(UnknownGame):
        registry.get("missing")
