"""Shared contract-suite coverage for the real Nim implementation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arena.core.exceptions import IllegalAction
from arena.core.results import Win
from arena.games.nim import (
    NIM_GAME_ID,
    NimConfig,
    NimGameDefinition,
    NimState,
    TakeObjects,
)
from arena.testing import GameContractBundle, assert_game_contract


@dataclass(frozen=True)
class NimContractBundle:
    """Test-local adapter that satisfies the shared game contract."""

    definition: object
    config: NimConfig
    initial_state: NimState
    near_terminal_state: NimState
    terminal_state: NimState
    legal_action: TakeObjects
    illegal_action: TakeObjects


def build_nim_contract_bundle() -> GameContractBundle:
    """Build a contract bundle from the registry-facing Nim definition."""

    definition = NimGameDefinition
    config = definition.config_type()
    rules_engine = definition.rules_engine
    legal_action = TakeObjects(pile_index=0, count=1)
    illegal_action = TakeObjects(pile_index=config.num_piles, count=1)

    initial_state = rules_engine.initial_state(config)
    near_terminal_state = NimState(
        piles=(1,) + (0,) * (config.num_piles - 1),
        current_seat=0,
    )
    terminal_state = rules_engine.apply_action(near_terminal_state, 0, legal_action).state

    return NimContractBundle(
        definition=definition,
        config=config,
        initial_state=initial_state,
        near_terminal_state=near_terminal_state,
        terminal_state=terminal_state,
        legal_action=legal_action,
        illegal_action=illegal_action,
    )


def test_nim_contract_bundle_passes_the_shared_contract_suite() -> None:
    bundle = build_nim_contract_bundle()

    assert bundle.definition is NimGameDefinition
    assert bundle.definition.game_id == NIM_GAME_ID

    assert_game_contract(bundle)


def test_nim_contract_bundle_near_terminal_fixture_reaches_terminal_state() -> None:
    bundle = build_nim_contract_bundle()
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


def test_nim_contract_bundle_illegal_action_is_rejected_from_the_initial_state() -> None:
    bundle = build_nim_contract_bundle()
    rules_engine = bundle.definition.rules_engine
    initial_seat = rules_engine.current_seat(bundle.initial_state)

    assert bundle.illegal_action == TakeObjects(pile_index=bundle.config.num_piles, count=1)

    with pytest.raises(IllegalAction):
        rules_engine.validate_action(bundle.initial_state, initial_seat, bundle.illegal_action)

    with pytest.raises(IllegalAction):
        rules_engine.apply_action(bundle.initial_state, initial_seat, bundle.illegal_action)
