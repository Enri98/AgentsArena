"""Tests for the Nim serializer boundary."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from arena.core.serializer import Serializer
from arena.games.nim import (
    NimConfig,
    NimObservation,
    NimRulesEngine,
    NimSerializer,
    NimState,
    TakeObjects,
)
from arena.games.nim import __all__ as nim_exports
from arena.games.nim.serializer import (
    NimConfigPayload,
    NimObservationPayload,
    NimStatePayload,
    TakeObjectsPayload,
)


def test_nim_serializer_is_importable_and_satisfies_shared_contract() -> None:
    serializer = NimSerializer()

    assert NimSerializer.__name__ == "NimSerializer"
    assert isinstance(serializer, Serializer)


def test_nim_serializer_round_trips_config() -> None:
    serializer = NimSerializer()
    config = NimConfig(num_piles=3, max_pile_size=7)

    assert serializer.load_config(serializer.dump_config(config)) == config


def test_nim_serializer_dumps_json_friendly_config() -> None:
    serializer = NimSerializer()
    payload = serializer.dump_config(NimConfig())

    assert payload == {"num_piles": 3, "max_pile_size": 7}
    assert json.loads(json.dumps(payload)) == payload


def test_nim_serializer_round_trips_action() -> None:
    serializer = NimSerializer()

    for action in (TakeObjects(pile_index=0, count=1), TakeObjects(pile_index=2, count=5)):
        assert serializer.load_action(serializer.dump_action(action)) == action


def test_nim_serializer_dumps_json_friendly_action() -> None:
    serializer = NimSerializer()
    payload = serializer.dump_action(TakeObjects(pile_index=1, count=3))

    assert payload == {"pile_index": 1, "count": 3}
    assert json.loads(json.dumps(payload)) == payload


def test_nim_serializer_round_trips_state() -> None:
    serializer = NimSerializer()
    rules = NimRulesEngine()
    config = NimConfig(num_piles=3, max_pile_size=5)
    initial = rules.initial_state(config)
    after_move = rules.apply_action(initial, 0, TakeObjects(pile_index=0, count=2)).state

    for state in (initial, after_move):
        rehydrated = serializer.load_state(serializer.dump_state(state))
        assert rehydrated == state
        assert isinstance(rehydrated.piles, tuple)


def test_nim_serializer_dumps_json_friendly_state() -> None:
    serializer = NimSerializer()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    payload = serializer.dump_state(state)

    assert payload == {"piles": [3, 5, 7], "current_seat": 0}
    assert json.loads(json.dumps(payload)) == payload


def test_nim_serializer_round_trips_observation() -> None:
    serializer = NimSerializer()
    obs = NimObservation(
        seat=0,
        piles=(3, 5, 7),
        current_seat=0,
        legal_actions=(
            TakeObjects(pile_index=0, count=1),
            TakeObjects(pile_index=0, count=2),
        ),
    )

    rehydrated = serializer.load_observation(serializer.dump_observation(obs))
    assert rehydrated == obs


def test_nim_serializer_dumps_json_friendly_observation() -> None:
    serializer = NimSerializer()
    obs = NimObservation(
        seat=0,
        piles=(3, 5, 7),
        current_seat=0,
        legal_actions=(TakeObjects(pile_index=0, count=1),),
    )

    payload = serializer.dump_observation(obs)

    assert payload == {
        "seat": 0,
        "piles": [3, 5, 7],
        "current_seat": 0,
        "legal_actions": [{"pile_index": 0, "count": 1}],
    }
    assert json.loads(json.dumps(payload)) == payload


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"num_piles": 0, "max_pile_size": 7}, "num_piles"),
        ({"num_piles": 3, "max_pile_size": 0}, "max_pile_size"),
        ({"num_piles": "3", "max_pile_size": 7}, "num_piles"),
        ({"num_piles": 3, "max_pile_size": 7, "extra": True}, "extra"),
    ],
)
def test_nim_serializer_load_config_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = NimSerializer()

    with pytest.raises(ValidationError) as exc_info:
        serializer.load_config(payload)

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({}, "pile_index"),
        ({"pile_index": -1, "count": 1}, "pile_index"),
        ({"pile_index": 0, "count": 0}, "count"),
        ({"pile_index": "0", "count": 1}, "pile_index"),
        ({"pile_index": 0, "count": 1, "extra": True}, "extra"),
    ],
)
def test_nim_serializer_load_action_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = NimSerializer()

    with pytest.raises(ValidationError) as exc_info:
        serializer.load_action(payload)

    assert field_name in str(exc_info.value)


def test_nim_serializer_boundary_models_can_emit_json_schema() -> None:
    config_schema = NimConfigPayload.model_json_schema()
    action_schema = TakeObjectsPayload.model_json_schema()
    state_schema = NimStatePayload.model_json_schema()
    observation_schema = NimObservationPayload.model_json_schema()

    assert config_schema["title"] == "NimConfigPayload"
    assert "num_piles" in config_schema["properties"]
    assert "max_pile_size" in config_schema["properties"]
    assert action_schema["title"] == "TakeObjectsPayload"
    assert state_schema["title"] == "NimStatePayload"
    assert observation_schema["title"] == "NimObservationPayload"


def test_nim_package_exports_serializer_surface() -> None:
    assert "NimSerializer" in nim_exports
