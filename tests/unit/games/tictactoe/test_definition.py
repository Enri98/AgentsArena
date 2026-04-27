"""Tests for the Tic-Tac-Toe registry-facing definition."""

from __future__ import annotations

import pytest

from arena.core.exceptions import DuplicateGameRegistration
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.tictactoe import (
    TICTACTOE_GAME_ID,
    PlaceMark,
    TicTacToeConfig,
    TicTacToeGameDefinition,
    TicTacToeObservation,
    TicTacToeRulesEngine,
    TicTacToeSerializer,
    TicTacToeState,
    register_tictactoe,
)


def test_tictactoe_definition_wires_the_expected_domain_types() -> None:
    definition = TicTacToeGameDefinition

    assert definition.game_id == TICTACTOE_GAME_ID
    assert definition.display_name == "Tic-Tac-Toe"
    assert definition.config_type is TicTacToeConfig
    assert definition.state_type is TicTacToeState
    assert definition.action_type is PlaceMark
    assert definition.observation_type is TicTacToeObservation
    assert definition.result_type is RuleResult
    assert isinstance(definition.rules_engine, TicTacToeRulesEngine)
    assert isinstance(definition.serializer, TicTacToeSerializer)


def test_register_tictactoe_makes_the_definition_discoverable_through_the_registry() -> None:
    registry = GameRegistry()

    register_tictactoe(registry)

    definition = registry.get(TICTACTOE_GAME_ID)
    config = definition.config_type()
    state = definition.rules_engine.initial_state(config)

    assert definition is TicTacToeGameDefinition
    assert state.board == (
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
    )
    assert state.current_seat == 0
    assert definition.rules_engine.current_seat(state) == 0
    assert definition.rules_engine.legal_actions(state, 0) == tuple(
        PlaceMark(row=row, column=column) for row in range(3) for column in range(3)
    )
    assert definition.serializer.load_state(definition.serializer.dump_state(state)) == state


def test_register_tictactoe_rejects_duplicate_registration() -> None:
    registry = GameRegistry()

    register_tictactoe(registry)

    with pytest.raises(DuplicateGameRegistration):
        register_tictactoe(registry)
