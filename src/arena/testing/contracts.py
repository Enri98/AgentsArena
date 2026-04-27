"""Reusable contract assertions for game implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from arena.core.exceptions import ArenaCoreError
from arena.core.seats import is_seat
from arena.core.serializer import Serializer


@runtime_checkable
class GameContractBundle(Protocol):
    """Fixture bundle contract used by the shared game-contract assertions."""

    definition: object
    config: object
    initial_state: object
    near_terminal_state: object
    terminal_state: object
    legal_action: object
    illegal_action: object


def assert_valid_initial_state(bundle: GameContractBundle) -> None:
    """Assert that a game exposes a coherent validated initial state."""

    rules_engine = bundle.definition.rules_engine
    initial_state = rules_engine.initial_state(bundle.config)

    assert initial_state == bundle.initial_state, (
        "initial state contract failed: rules engine did not reproduce the bundle's "
        "initial_state from the provided config"
    )

    seat = rules_engine.current_seat(initial_state)
    assert is_seat(seat), "initial state contract failed: current_seat must return a valid seat id"
    assert not rules_engine.is_terminal(initial_state), (
        "initial state contract failed: initial_state must not be terminal"
    )
    assert rules_engine.result(initial_state) is None, (
        "initial state contract failed: initial_state must not report a terminal result"
    )


def assert_legal_action_generation(bundle: GameContractBundle) -> None:
    """Assert that ongoing states expose valid legal actions."""

    rules_engine = bundle.definition.rules_engine
    state = bundle.initial_state
    seat = rules_engine.current_seat(state)
    legal_actions = rules_engine.legal_actions(state, seat)
    action_type = bundle.definition.action_type

    assert legal_actions, (
        "legal action generation contract failed: ongoing states must expose "
        "at least one legal action"
    )
    assert bundle.legal_action in legal_actions, (
        "legal action generation contract failed: bundle.legal_action must be "
        "present in legal_actions"
    )

    for action in legal_actions:
        assert isinstance(action, action_type), (
            "legal action generation contract failed: legal actions must match the game "
            "definition's declared action_type"
        )
        try:
            rules_engine.validate_action(state, seat, action)
        except ArenaCoreError as exc:  # pragma: no cover - exercised by negative tests
            raise AssertionError(
                "legal action generation contract failed: legal actions must validate successfully"
            ) from exc


def assert_illegal_action_rejection(bundle: GameContractBundle) -> None:
    """Assert that intentionally illegal actions fail predictably."""

    rules_engine = bundle.definition.rules_engine
    state = bundle.initial_state
    seat = rules_engine.current_seat(state)

    try:
        rules_engine.validate_action(state, seat, bundle.illegal_action)
    except ArenaCoreError:
        pass
    else:  # pragma: no cover - exercised by negative tests
        raise AssertionError(
            "illegal action rejection contract failed: bundle.illegal_action "
            "must raise a domain error during validate_action"
        )

    try:
        rules_engine.apply_action(state, seat, bundle.illegal_action)
    except ArenaCoreError:
        return
    else:  # pragma: no cover - exercised by negative tests
        raise AssertionError(
            "illegal action rejection contract failed: apply_action must defensively reject "
            "bundle.illegal_action"
        )


def assert_state_transition_behavior(bundle: GameContractBundle) -> None:
    """Assert that legal actions produce coherent transition results."""

    rules_engine = bundle.definition.rules_engine
    state = bundle.initial_state
    seat = rules_engine.current_seat(state)
    transition = rules_engine.apply_action(state, seat, bundle.legal_action)

    assert transition.state != state, (
        "state transition contract failed: applying a legal action must produce a new state"
    )
    assert isinstance(transition.events, tuple), (
        "state transition contract failed: emitted events must be exposed as an immutable tuple"
    )
    assert transition.result == rules_engine.result(transition.state), (
        "state transition contract failed: transition.result must match "
        "rules_engine.result(next_state)"
    )


def assert_terminal_result_consistency(bundle: GameContractBundle) -> None:
    """Assert that terminal fixtures and results stay coherent."""

    rules_engine = bundle.definition.rules_engine
    near_terminal_seat = rules_engine.current_seat(bundle.near_terminal_state)
    transition = rules_engine.apply_action(
        bundle.near_terminal_state,
        near_terminal_seat,
        bundle.legal_action,
    )

    assert transition.state == bundle.terminal_state, (
        "terminal/result contract failed: near_terminal_state should reach terminal_state via "
        "bundle.legal_action"
    )
    assert rules_engine.is_terminal(bundle.terminal_state), (
        "terminal/result contract failed: terminal_state must be terminal"
    )
    assert transition.result == rules_engine.result(bundle.terminal_state), (
        "terminal/result contract failed: transition.result must match "
        "rules_engine.result(terminal_state)"
    )
    assert not rules_engine.legal_actions(
        bundle.terminal_state,
        rules_engine.current_seat(bundle.terminal_state),
    ), "terminal/result contract failed: terminal states must not expose legal actions"


def assert_serialization_round_trip(bundle: GameContractBundle) -> None:
    """Assert that serializer round-trips preserve game semantics."""

    serializer = bundle.definition.serializer
    rules_engine = bundle.definition.rules_engine

    assert isinstance(serializer, Serializer), (
        "serialization round-trip contract failed: game definition must expose a shared Serializer"
    )

    rehydrated_config = serializer.load_config(serializer.dump_config(bundle.config))
    assert rehydrated_config == bundle.config, (
        "serialization round-trip contract failed: config round-trip must "
        "preserve the validated config"
    )

    rehydrated_state = serializer.load_state(serializer.dump_state(bundle.near_terminal_state))
    assert _state_semantics_match(
        rules_engine,
        bundle.near_terminal_state,
        rehydrated_state,
    ), (
        "serialization round-trip contract failed: rehydrated state must "
        "behave like the original state"
    )

    rehydrated_action = serializer.load_action(serializer.dump_action(bundle.legal_action))
    assert rehydrated_action == bundle.legal_action, (
        "serialization round-trip contract failed: action round-trip must preserve the legal action"
    )

    observation = rules_engine.observation(
        bundle.initial_state,
        rules_engine.current_seat(bundle.initial_state),
    )
    rehydrated_observation = serializer.load_observation(serializer.dump_observation(observation))
    assert rehydrated_observation == observation, (
        "serialization round-trip contract failed: observation round-trip "
        "must preserve observation data"
    )


def assert_game_contract(bundle: GameContractBundle) -> None:
    """Run the full reusable contract suite against a game bundle."""

    assert_valid_initial_state(bundle)
    assert_legal_action_generation(bundle)
    assert_illegal_action_rejection(bundle)
    assert_state_transition_behavior(bundle)
    assert_terminal_result_consistency(bundle)
    assert_serialization_round_trip(bundle)


def _state_semantics_match(
    rules_engine: object,
    original_state: object,
    rehydrated_state: object,
) -> bool:
    """Compare public state semantics through the shared rules-engine contract."""

    original_is_terminal = rules_engine.is_terminal(original_state)
    rehydrated_is_terminal = rules_engine.is_terminal(rehydrated_state)
    if original_is_terminal != rehydrated_is_terminal:
        return False

    if rules_engine.result(original_state) != rules_engine.result(rehydrated_state):
        return False

    if original_is_terminal:
        return True

    original_seat = rules_engine.current_seat(original_state)
    rehydrated_seat = rules_engine.current_seat(rehydrated_state)
    if original_seat != rehydrated_seat:
        return False

    original_actions = rules_engine.legal_actions(original_state, original_seat)
    rehydrated_actions = rules_engine.legal_actions(rehydrated_state, rehydrated_seat)
    if original_actions != rehydrated_actions:
        return False

    original_observation = rules_engine.observation(original_state, original_seat)
    rehydrated_observation = rules_engine.observation(rehydrated_state, rehydrated_seat)
    return original_observation == rehydrated_observation


__all__: Sequence[str] = [
    "GameContractBundle",
    "assert_game_contract",
    "assert_illegal_action_rejection",
    "assert_legal_action_generation",
    "assert_serialization_round_trip",
    "assert_state_transition_behavior",
    "assert_terminal_result_consistency",
    "assert_valid_initial_state",
]
