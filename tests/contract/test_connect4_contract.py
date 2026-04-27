"""Shared contract-suite coverage for the real Connect 4 implementation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arena.core.exceptions import IllegalAction
from arena.core.results import Win
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    Connect4State,
    DropDisc,
)
from arena.testing import GameContractBundle, assert_game_contract


@dataclass(frozen=True)
class Connect4ContractBundle:
    """Test-local adapter that satisfies the shared game contract."""

    definition: object
    config: Connect4Config
    initial_state: Connect4State
    near_terminal_state: Connect4State
    terminal_state: Connect4State
    legal_action: DropDisc
    illegal_action: DropDisc


def build_connect4_contract_bundle() -> GameContractBundle:
    """Build a contract bundle from the registry-facing Connect 4 definition."""

    definition = Connect4GameDefinition
    config = definition.config_type()
    rules_engine = definition.rules_engine
    legal_action = DropDisc(column=0)
    illegal_action = DropDisc(column=config.columns)

    initial_state = rules_engine.initial_state(config)
    near_terminal_state = Connect4State(
        board=(
            (0, 0, 0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0, 0, 0),
            (1, 0, 0, 0, 0, 0, 0),
            (1, 0, 0, 0, 0, 0, 0),
            (1, 0, 0, 0, 0, 0, 0),
        ),
        current_seat=0,
    )
    terminal_state = rules_engine.apply_action(near_terminal_state, 0, legal_action).state

    return Connect4ContractBundle(
        definition=definition,
        config=config,
        initial_state=initial_state,
        near_terminal_state=near_terminal_state,
        terminal_state=terminal_state,
        legal_action=legal_action,
        illegal_action=illegal_action,
    )


def test_connect4_contract_bundle_passes_the_shared_contract_suite() -> None:
    bundle = build_connect4_contract_bundle()

    assert bundle.definition is Connect4GameDefinition
    assert bundle.definition.game_id == CONNECT4_GAME_ID

    assert_game_contract(bundle)


def test_connect4_contract_bundle_near_terminal_fixture_reaches_terminal_state() -> None:
    bundle = build_connect4_contract_bundle()
    rules_engine = bundle.definition.rules_engine
    near_terminal_seat = rules_engine.current_seat(bundle.near_terminal_state)

    transition = rules_engine.apply_action(
        bundle.near_terminal_state,
        near_terminal_seat,
        bundle.legal_action,
    )

    assert transition.state == bundle.terminal_state
    assert transition.result == Win(seat=0)
    assert rules_engine.result(bundle.terminal_state) == Win(seat=0)


def test_connect4_contract_bundle_illegal_action_is_rejected_from_the_initial_state() -> None:
    bundle = build_connect4_contract_bundle()
    rules_engine = bundle.definition.rules_engine
    initial_seat = rules_engine.current_seat(bundle.initial_state)

    assert bundle.illegal_action == DropDisc(column=bundle.config.columns)

    with pytest.raises(IllegalAction):
        rules_engine.validate_action(bundle.initial_state, initial_seat, bundle.illegal_action)

    with pytest.raises(IllegalAction):
        rules_engine.apply_action(bundle.initial_state, initial_seat, bundle.illegal_action)
