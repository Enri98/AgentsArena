"""Tests for reusable game-contract assertions."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from arena.core.actions import Action
from arena.testing import (
    assert_game_contract,
    assert_illegal_action_rejection,
    assert_legal_action_generation,
    assert_serialization_round_trip,
    build_fake_game_bundle,
)
from arena.testing.factories import FakeAction, FakeRulesEngine, FakeSerializer, FakeState


@dataclass(frozen=True)
class EquivalentState(FakeState):
    """State with matching public semantics but a distinct runtime type."""


@dataclass(frozen=True)
class WrongAction(Action):
    """Action with the right payload shape but the wrong declared type."""

    amount: int


class BrokenIllegalActionBundleSerializer(FakeSerializer):
    """Serializer variant used to force a state round-trip mismatch in tests."""

    def load_state(self, payload: dict[str, object]) -> object:
        state = super().load_state(payload)
        return replace(state, turn=0)


class SemanticallyEquivalentSerializer(FakeSerializer):
    """Serializer variant that rehydrates to a non-equal but behaviorally equivalent state."""

    def load_state(self, payload: dict[str, object]) -> object:
        state = super().load_state(payload)
        return EquivalentState(turn=state.turn, max_turns=state.max_turns)


class WrongActionTypeRulesEngine(FakeRulesEngine):
    """Rules engine variant used to surface action-type mismatches."""

    def legal_actions(self, state: FakeState, seat: int) -> tuple[WrongAction, ...]:
        return (WrongAction(amount=1),)

    def validate_action(self, state: FakeState, seat: int, action: WrongAction) -> None:
        if action.amount != 1:
            super().validate_action(state, seat, FakeAction(amount=action.amount))


def test_full_contract_suite_passes_for_the_fake_game_bundle() -> None:
    bundle = build_fake_game_bundle()

    assert_game_contract(bundle)


def test_illegal_action_failure_message_is_understandable() -> None:
    bundle = build_fake_game_bundle()
    broken_bundle = replace(bundle, illegal_action=bundle.legal_action)

    with pytest.raises(AssertionError, match="illegal action rejection contract failed"):
        assert_illegal_action_rejection(broken_bundle)


def test_legal_action_generation_failure_message_is_understandable_for_wrong_action_types() -> None:
    bundle = build_fake_game_bundle()
    broken_definition = replace(
        bundle.definition,
        rules_engine=WrongActionTypeRulesEngine(),
    )
    broken_bundle = replace(
        bundle,
        definition=broken_definition,
        legal_action=WrongAction(amount=1),
    )

    with pytest.raises(AssertionError, match="legal action generation contract failed"):
        assert_legal_action_generation(broken_bundle)


def test_serialization_failure_message_is_understandable() -> None:
    bundle = build_fake_game_bundle()
    broken_definition = replace(
        bundle.definition,
        serializer=BrokenIllegalActionBundleSerializer(),
    )
    broken_bundle = replace(bundle, definition=broken_definition)

    with pytest.raises(AssertionError, match="serialization round-trip contract failed"):
        assert_serialization_round_trip(broken_bundle)


def test_serialization_round_trip_accepts_semantically_equivalent_non_equal_states() -> None:
    bundle = build_fake_game_bundle()
    equivalent_definition = replace(
        bundle.definition,
        serializer=SemanticallyEquivalentSerializer(),
    )
    equivalent_bundle = replace(bundle, definition=equivalent_definition)

    assert_serialization_round_trip(equivalent_bundle)
