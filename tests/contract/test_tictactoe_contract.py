"""Shared contract-suite coverage for the real Tic-Tac-Toe implementation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arena.core.exceptions import IllegalAction
from arena.core.results import Win
from arena.games.tictactoe import (
    TICTACTOE_GAME_ID,
    PlaceMark,
    TicTacToeConfig,
    TicTacToeGameDefinition,
    TicTacToeState,
)
from arena.testing import GameContractBundle, assert_game_contract


@dataclass(frozen=True)
class TicTacToeContractBundle:
    """Test-local adapter that satisfies the shared game contract."""

    definition: object
    config: TicTacToeConfig
    initial_state: TicTacToeState
    near_terminal_state: TicTacToeState
    terminal_state: TicTacToeState
    legal_action: PlaceMark
    illegal_action: PlaceMark


def build_tictactoe_contract_bundle() -> GameContractBundle:
    """Build a contract bundle from the registry-facing Tic-Tac-Toe definition."""

    definition = TicTacToeGameDefinition
    config = definition.config_type()
    rules_engine = definition.rules_engine
    legal_action = PlaceMark(row=0, column=0)
    illegal_action = PlaceMark(row=3, column=0)

    initial_state = rules_engine.initial_state(config)
    near_terminal_state = TicTacToeState(
        board=(
            (0, 1, 1),
            (2, 2, 0),
            (0, 0, 0),
        ),
        current_seat=0,
    )
    terminal_state = rules_engine.apply_action(near_terminal_state, 0, legal_action).state

    return TicTacToeContractBundle(
        definition=definition,
        config=config,
        initial_state=initial_state,
        near_terminal_state=near_terminal_state,
        terminal_state=terminal_state,
        legal_action=legal_action,
        illegal_action=illegal_action,
    )


def test_tictactoe_contract_bundle_passes_the_shared_contract_suite() -> None:
    bundle = build_tictactoe_contract_bundle()

    assert bundle.definition is TicTacToeGameDefinition
    assert bundle.definition.game_id == TICTACTOE_GAME_ID

    assert_game_contract(bundle)


def test_tictactoe_contract_bundle_near_terminal_fixture_reaches_terminal_state() -> None:
    bundle = build_tictactoe_contract_bundle()
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


def test_tictactoe_contract_bundle_illegal_action_is_rejected_from_the_initial_state() -> None:
    bundle = build_tictactoe_contract_bundle()
    rules_engine = bundle.definition.rules_engine
    initial_seat = rules_engine.current_seat(bundle.initial_state)

    with pytest.raises(IllegalAction):
        rules_engine.validate_action(bundle.initial_state, initial_seat, bundle.illegal_action)

    with pytest.raises(IllegalAction):
        rules_engine.apply_action(bundle.initial_state, initial_seat, bundle.illegal_action)
