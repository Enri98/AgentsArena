"""Shared contract-suite coverage for Rock-Paper-Scissors (Phase 41).

The suite applies a bundle action as the acting seat would; at a joint node
every acting seat plays it, so the bundle's actions are throws any seat makes.
"""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.results import Draw
from arena.games.pig import PigMove
from arena.games.rps import (
    RPS_GAME_ID,
    RoundResult,
    RpsConfig,
    RpsGameDefinition,
    RpsState,
    Throw,
)
from arena.testing import GameContractBundle, assert_game_contract


@dataclass(frozen=True)
class RpsContractBundle:
    definition: object
    config: RpsConfig
    initial_state: RpsState
    near_terminal_state: RpsState
    terminal_state: RpsState
    legal_action: Throw
    illegal_action: object


def build_rps_contract_bundle() -> GameContractBundle:
    definition = RpsGameDefinition
    config = RpsConfig(target_wins=3, max_rounds=5)
    rules_engine = definition.rules_engine
    # One round from the cap; both seats throwing rock ties it: a draw.
    near_terminal_state = RpsState(
        wins=(1, 1),
        rounds_played=4,
        target_wins=3,
        max_rounds=5,
        last_round=RoundResult(("rock", "rock"), None),
    )
    legal_action = Throw("rock")
    terminal_state = rules_engine.apply_joint_action(
        near_terminal_state, {0: legal_action, 1: legal_action}
    ).state
    return RpsContractBundle(
        definition=definition,
        config=config,
        initial_state=rules_engine.initial_state(config),
        near_terminal_state=near_terminal_state,
        terminal_state=terminal_state,
        legal_action=legal_action,
        illegal_action=PigMove(choice="roll"),  # not a throw
    )


def test_rps_passes_the_shared_contract_suite() -> None:
    bundle = build_rps_contract_bundle()
    assert bundle.definition.game_id == RPS_GAME_ID
    assert bundle.definition.has_simultaneous_moves is True
    assert_game_contract(bundle)


def test_the_near_terminal_fixture_draws() -> None:
    bundle = build_rps_contract_bundle()
    assert bundle.definition.rules_engine.result(bundle.terminal_state) == Draw()
