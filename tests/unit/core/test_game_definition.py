"""Tests for shared game definition contracts."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import Draw
from arena.core.rules_engine import RulesEngine, TransitionResult
from arena.core.serializer import JSONMapping, Serializer


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


def test_game_definition_holds_registry_facing_metadata() -> None:
    definition = GameDefinition(
        game_id="example",
        display_name="Example",
        config_type=ExampleConfig,
        state_type=ExampleState,
        action_type=ExampleAction,
        observation_type=ExampleObservation,
        rules_engine=ExampleRulesEngine(),
        serializer=ExampleSerializer(),
        result_type=Draw,
    )

    assert definition.game_id == "example"
    assert definition.display_name == "Example"
    assert definition.config_type is ExampleConfig
    assert definition.action_type is ExampleAction
    assert definition.result_type is Draw


def test_game_definition_wiring_matches_shared_contracts() -> None:
    definition = GameDefinition(
        game_id="example",
        display_name="Example",
        config_type=ExampleConfig,
        state_type=ExampleState,
        action_type=ExampleAction,
        observation_type=ExampleObservation,
        rules_engine=ExampleRulesEngine(),
        serializer=ExampleSerializer(),
        result_type=Draw,
    )

    assert isinstance(definition.rules_engine, RulesEngine)
    assert isinstance(definition.serializer, Serializer)
