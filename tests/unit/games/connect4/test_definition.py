"""Tests for the Connect 4 registry-facing definition."""

from __future__ import annotations

import pytest

from arena.core.exceptions import DuplicateGameRegistration
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    Connect4RulesEngine,
    Connect4Serializer,
    Connect4State,
    DropDisc,
    register_connect4,
)


def test_connect4_definition_wires_the_expected_domain_types() -> None:
    definition = Connect4GameDefinition

    assert definition.game_id == CONNECT4_GAME_ID
    assert definition.display_name == "Connect 4"
    assert definition.config_type is Connect4Config
    assert definition.state_type is Connect4State
    assert definition.action_type is DropDisc
    assert definition.observation_type is Connect4Observation
    assert definition.result_type is RuleResult
    assert isinstance(definition.rules_engine, Connect4RulesEngine)
    assert isinstance(definition.serializer, Connect4Serializer)


def test_register_connect4_makes_the_definition_discoverable_through_the_registry() -> None:
    registry = GameRegistry()

    register_connect4(registry)

    definition = registry.get(CONNECT4_GAME_ID)
    config = definition.config_type()
    state = definition.rules_engine.initial_state(config)

    assert definition is Connect4GameDefinition
    assert state.board == tuple(
        tuple(0 for _ in range(config.columns))
        for _ in range(config.rows)
    )
    assert state.current_seat == 0
    assert definition.rules_engine.current_seat(state) == 0
    assert definition.rules_engine.legal_actions(state, 0) == tuple(
        DropDisc(column=column) for column in range(config.columns)
    )
    assert definition.serializer.load_state(definition.serializer.dump_state(state)) == state


def test_register_connect4_rejects_duplicate_registration() -> None:
    registry = GameRegistry()

    register_connect4(registry)

    with pytest.raises(DuplicateGameRegistration):
        register_connect4(registry)
