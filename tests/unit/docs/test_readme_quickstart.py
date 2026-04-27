"""Test-backed examples for the README quickstart flow."""

from __future__ import annotations

from arena.core import GameRegistry
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    DropDisc,
    register_connect4,
)


def test_readme_quickstart_flow_matches_the_public_connect4_api() -> None:
    registry = GameRegistry()
    register_connect4(registry)

    definition = registry.get(CONNECT4_GAME_ID)
    config = Connect4Config()

    state = definition.rules_engine.initial_state(config)
    legal_actions = definition.rules_engine.legal_actions(state, state.current_seat)

    assert legal_actions == tuple(
        DropDisc(column=column) for column in range(config.columns)
    )

    move = legal_actions[0]
    transition = definition.rules_engine.apply_action(state, state.current_seat, move)
    next_state = transition.state

    assert next_state.current_seat == 1
    assert next_state.board[-1][0] == 1

    state_payload = definition.serializer.dump_state(next_state)
    rehydrated_state = definition.serializer.load_state(state_payload)
    assert rehydrated_state == next_state

    config_payload = definition.serializer.dump_config(config)
    rehydrated_config = definition.serializer.load_config(config_payload)
    assert rehydrated_config == config
