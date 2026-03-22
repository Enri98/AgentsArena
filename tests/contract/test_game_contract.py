"""Shared contract-suite entry point for reusable game validation."""

from arena.testing import assert_game_contract, build_fake_game_bundle


def test_fake_game_bundle_satisfies_the_shared_game_contract() -> None:
    """Run the full shared contract suite against the fake game bundle."""

    bundle = build_fake_game_bundle()

    assert_game_contract(bundle)


def test_shared_game_contract_is_deterministic_across_fresh_fake_game_bundles() -> None:
    """Prove the reusable contract suite behaves deterministically across fresh fixtures."""

    first_bundle = build_fake_game_bundle()
    second_bundle = build_fake_game_bundle()

    assert first_bundle.config == second_bundle.config
    assert first_bundle.initial_state == second_bundle.initial_state
    assert first_bundle.near_terminal_state == second_bundle.near_terminal_state
    assert first_bundle.terminal_state == second_bundle.terminal_state
    assert first_bundle.legal_action == second_bundle.legal_action
    assert first_bundle.illegal_action == second_bundle.illegal_action
    assert first_bundle.definition.game_id == second_bundle.definition.game_id
    assert first_bundle.definition.action_type is second_bundle.definition.action_type
    assert first_bundle.definition.result_type is second_bundle.definition.result_type

    assert_game_contract(first_bundle)
    assert_game_contract(second_bundle)
