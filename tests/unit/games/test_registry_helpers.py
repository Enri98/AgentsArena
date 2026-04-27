"""Tests for built-in game registry convenience helpers."""

from __future__ import annotations

import pytest

from arena.core.exceptions import DuplicateGameRegistration
from arena.core.registry import GameRegistry
from arena.games import build_default_registry, register_builtin_games
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    DropDisc,
)
from arena.games.tictactoe import (
    TICTACTOE_GAME_ID,
    PlaceMark,
    TicTacToeConfig,
    TicTacToeGameDefinition,
)


def test_build_default_registry_contains_connect4_and_tictactoe_and_resolves_definition_wiring(
) -> None:
    registry = build_default_registry()

    connect4_definition = registry.get(CONNECT4_GAME_ID)
    tictactoe_definition = registry.get(TICTACTOE_GAME_ID)

    connect4_config = Connect4Config()
    connect4_state = connect4_definition.rules_engine.initial_state(connect4_config)
    connect4_legal_actions = connect4_definition.rules_engine.legal_actions(
        connect4_state,
        connect4_state.current_seat,
    )
    connect4_transition = connect4_definition.rules_engine.apply_action(
        connect4_state,
        connect4_state.current_seat,
        connect4_legal_actions[0],
    )

    tictactoe_config = TicTacToeConfig()
    tictactoe_state = tictactoe_definition.rules_engine.initial_state(tictactoe_config)
    tictactoe_legal_actions = tictactoe_definition.rules_engine.legal_actions(
        tictactoe_state,
        tictactoe_state.current_seat,
    )
    tictactoe_transition = tictactoe_definition.rules_engine.apply_action(
        tictactoe_state,
        tictactoe_state.current_seat,
        tictactoe_legal_actions[0],
    )

    assert connect4_definition is Connect4GameDefinition
    assert connect4_legal_actions == tuple(
        DropDisc(column=column) for column in range(connect4_config.columns)
    )
    assert (
        connect4_definition.serializer.load_config(
            connect4_definition.serializer.dump_config(connect4_config)
        )
        == connect4_config
    )
    assert (
        connect4_definition.serializer.load_state(
            connect4_definition.serializer.dump_state(connect4_transition.state)
        )
        == connect4_transition.state
    )

    assert tictactoe_definition is TicTacToeGameDefinition
    assert tictactoe_legal_actions == tuple(
        PlaceMark(row=row, column=column) for row in range(3) for column in range(3)
    )
    assert (
        tictactoe_definition.serializer.load_config(
            tictactoe_definition.serializer.dump_config(tictactoe_config)
        )
        == tictactoe_config
    )
    assert (
        tictactoe_definition.serializer.load_state(
            tictactoe_definition.serializer.dump_state(tictactoe_transition.state)
        )
        == tictactoe_transition.state
    )


def test_register_builtin_games_preserves_duplicate_registration_behavior() -> None:
    registry = GameRegistry()

    register_builtin_games(registry)

    with pytest.raises(DuplicateGameRegistration):
        register_builtin_games(registry)
