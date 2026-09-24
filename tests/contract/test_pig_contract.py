"""Shared contract-suite coverage for Pig, including the chance contract."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.results import Win
from arena.games.pig import (
    HOLD,
    PIG_GAME_ID,
    ROLL,
    PigConfig,
    PigGameDefinition,
    PigMove,
    PigState,
)
from arena.testing import GameContractBundle, assert_chance_contract, assert_game_contract


@dataclass(frozen=True)
class PigContractBundle:
    definition: object
    config: PigConfig
    initial_state: PigState
    near_terminal_state: PigState
    terminal_state: PigState
    legal_action: PigMove
    illegal_action: PigMove
    terminal_action: PigMove


def build_pig_contract_bundle() -> GameContractBundle:
    definition = PigGameDefinition
    config = PigConfig()
    rules_engine = definition.rules_engine

    near_terminal_state = PigState(
        scores=(config.target_score - 5, 0),
        current_seat=0,
        turn_total=5,
        roll_pending=False,
        target_score=config.target_score,
    )
    terminal_action = PigMove(choice=HOLD)
    terminal_state = rules_engine.apply_action(near_terminal_state, 0, terminal_action).state

    return PigContractBundle(
        definition=definition,
        config=config,
        initial_state=rules_engine.initial_state(config),
        near_terminal_state=near_terminal_state,
        terminal_state=terminal_state,
        # Only a roll is legal as a turn opens; only a hold can end the game.
        legal_action=PigMove(choice=ROLL),
        illegal_action=PigMove(choice=HOLD),
        terminal_action=terminal_action,
    )


def test_pig_passes_the_shared_contract_suite() -> None:
    bundle = build_pig_contract_bundle()
    assert bundle.definition.game_id == PIG_GAME_ID
    assert bundle.definition.has_chance_nodes is True

    assert_game_contract(bundle)


def test_pig_passes_the_chance_contract() -> None:
    assert_chance_contract(build_pig_contract_bundle())


def test_near_terminal_fixture_wins_for_seat_0() -> None:
    bundle = build_pig_contract_bundle()
    assert bundle.definition.rules_engine.result(bundle.terminal_state) == Win(seat=0)
