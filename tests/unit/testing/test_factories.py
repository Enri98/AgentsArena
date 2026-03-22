"""Tests for shared fake-game factory helpers."""

from __future__ import annotations

from importlib import import_module

import pytest

from arena.core.exceptions import IllegalAction
from arena.core.results import Draw
from arena.core.rules_engine import TransitionResult
from arena.core.serializer import Serializer
from arena.testing import (
    FakeAction,
    FakeGameBundle,
    FakeGameConfig,
    FakeObservation,
    FakeState,
    build_fake_game_bundle,
)


def test_testing_package_exports_the_fake_game_helpers() -> None:
    module = import_module("arena.testing")

    assert module.__name__ == "arena.testing"
    assert module.build_fake_game_bundle is build_fake_game_bundle


def test_fake_game_bundle_is_constructed_with_coherent_types() -> None:
    bundle = build_fake_game_bundle()

    assert isinstance(bundle, FakeGameBundle)
    assert isinstance(bundle.config, FakeGameConfig)
    assert bundle.definition.config_type is FakeGameConfig
    assert bundle.definition.state_type is FakeState
    assert bundle.definition.action_type is FakeAction
    assert bundle.definition.observation_type is FakeObservation
    assert bundle.definition.result_type is Draw
    assert isinstance(bundle.definition.serializer, Serializer)


def test_fake_game_bundle_produces_coherent_rules_engine_objects() -> None:
    bundle = build_fake_game_bundle()
    rules_engine = bundle.definition.rules_engine

    initial_state = rules_engine.initial_state(bundle.config)
    legal_actions = rules_engine.legal_actions(initial_state, seat=0)
    transition = rules_engine.apply_action(initial_state, seat=0, action=bundle.legal_action)
    observation = rules_engine.observation(transition.state, seat=1)

    assert initial_state == bundle.initial_state
    assert legal_actions == (bundle.legal_action,)
    assert isinstance(transition, TransitionResult)
    assert transition.result is None
    assert observation == FakeObservation(seat=1, turn=1, remaining_turns=1)


def test_fake_game_bundle_locks_terminal_transition_fixtures() -> None:
    bundle = build_fake_game_bundle()
    rules_engine = bundle.definition.rules_engine

    transition = rules_engine.apply_action(
        bundle.near_terminal_state,
        seat=1,
        action=bundle.legal_action,
    )

    assert transition.state == bundle.terminal_state
    assert transition.result == Draw()
    assert rules_engine.is_terminal(bundle.terminal_state) is True
    assert rules_engine.result(bundle.terminal_state) == Draw()


def test_fake_game_bundle_rejects_the_illegal_action_fixture() -> None:
    bundle = build_fake_game_bundle()
    rules_engine = bundle.definition.rules_engine

    with pytest.raises(IllegalAction):
        rules_engine.validate_action(bundle.initial_state, seat=0, action=bundle.illegal_action)


def test_fake_game_bundle_serializer_round_trips_core_objects() -> None:
    bundle = build_fake_game_bundle()
    serializer = bundle.definition.serializer

    assert serializer.load_config(serializer.dump_config(bundle.config)) == bundle.config
    assert serializer.load_state(serializer.dump_state(bundle.near_terminal_state)) == bundle.near_terminal_state
    assert serializer.load_action(serializer.dump_action(bundle.legal_action)) == bundle.legal_action
    assert serializer.load_observation(
        serializer.dump_observation(FakeObservation(seat=1, turn=1, remaining_turns=1))
    ) == FakeObservation(seat=1, turn=1, remaining_turns=1)
