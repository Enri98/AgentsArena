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


def test_build_default_registry_contains_connect4_and_resolves_definition_wiring() -> None:
    registry = build_default_registry()

    definition = registry.get(CONNECT4_GAME_ID)
    config = Connect4Config()
    state = definition.rules_engine.initial_state(config)
    legal_actions = definition.rules_engine.legal_actions(state, state.current_seat)
    transition = definition.rules_engine.apply_action(state, state.current_seat, legal_actions[0])

    assert definition is Connect4GameDefinition
    assert legal_actions == tuple(DropDisc(column=column) for column in range(config.columns))
    assert definition.serializer.load_config(definition.serializer.dump_config(config)) == config
    assert (
        definition.serializer.load_state(definition.serializer.dump_state(transition.state))
        == transition.state
    )


def test_register_builtin_games_preserves_duplicate_registration_behavior() -> None:
    registry = GameRegistry()

    register_builtin_games(registry)

    with pytest.raises(DuplicateGameRegistration):
        register_builtin_games(registry)
