"""Shared testing helpers for game-contract validation."""

from arena.testing.contracts import (
    GameContractBundle,
    assert_game_contract,
    assert_illegal_action_rejection,
    assert_legal_action_generation,
    assert_serialization_round_trip,
    assert_state_transition_behavior,
    assert_terminal_result_consistency,
    assert_valid_initial_state,
)
from arena.testing.factories import (
    FakeAction,
    FakeGameBundle,
    FakeGameConfig,
    FakeObservation,
    FakeState,
    build_fake_game_bundle,
)

__all__ = [
    "FakeAction",
    "FakeGameBundle",
    "FakeGameConfig",
    "FakeObservation",
    "FakeState",
    "GameContractBundle",
    "assert_game_contract",
    "assert_illegal_action_rejection",
    "assert_legal_action_generation",
    "assert_serialization_round_trip",
    "assert_state_transition_behavior",
    "assert_terminal_result_consistency",
    "assert_valid_initial_state",
    "build_fake_game_bundle",
]
