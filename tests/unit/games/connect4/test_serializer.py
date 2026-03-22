"""Tests for the Connect 4 serializer boundary."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from arena.core.serializer import SnapshotEnvelope
from arena.core.serializer import Serializer
from arena.games.connect4 import (
    Connect4Config,
    Connect4Observation,
    Connect4Serializer,
    Connect4State,
    Connect4RulesEngine,
    DropDisc,
    EMPTY_CELL,
    SEAT0_DISC,
    SEAT1_DISC,
    __all__ as connect4_exports,
)
from arena.games.connect4.serializer import (
    Connect4ConfigPayload,
    Connect4ObservationPayload,
    Connect4StatePayload,
    DropDiscPayload,
)


def test_connect4_serializer_is_importable_and_satisfies_the_shared_contract() -> None:
    serializer = Connect4Serializer()

    assert Connect4Serializer.__name__ == "Connect4Serializer"
    assert isinstance(serializer, Serializer)


def test_connect4_serializer_round_trips_default_and_non_default_configs() -> None:
    serializer = Connect4Serializer()

    default_config = Connect4Config()
    custom_config = Connect4Config(rows=4, columns=5, connect_length=4)

    assert serializer.load_config(serializer.dump_config(default_config)) == default_config
    assert serializer.load_config(serializer.dump_config(custom_config)) == custom_config


def test_connect4_serializer_dumps_json_friendly_config_payloads() -> None:
    serializer = Connect4Serializer()
    payload = serializer.dump_config(Connect4Config(rows=4, columns=5, connect_length=4))

    assert payload == {"rows": 4, "columns": 5, "connect_length": 4}
    assert json.loads(json.dumps(payload)) == payload


def test_connect4_serializer_round_trips_boundary_drop_disc_actions() -> None:
    serializer = Connect4Serializer()

    for action in (DropDisc(column=0), DropDisc(column=6)):
        assert serializer.load_action(serializer.dump_action(action)) == action


def test_connect4_serializer_dumps_json_friendly_action_payloads() -> None:
    serializer = Connect4Serializer()
    payload = serializer.dump_action(DropDisc(column=3))

    assert payload == {"column": 3}
    assert json.loads(json.dumps(payload)) == payload


def test_connect4_serializer_round_trips_active_and_non_active_observations() -> None:
    serializer = Connect4Serializer()
    board = (
        (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        (EMPTY_CELL, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
        (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
    )

    active_observation = Connect4Observation(
        seat=0,
        board=board,
        current_seat=0,
        legal_actions=(
            DropDisc(column=0),
            DropDisc(column=1),
            DropDisc(column=2),
            DropDisc(column=3),
        ),
    )
    non_active_observation = Connect4Observation(
        seat=1,
        board=board,
        current_seat=0,
        legal_actions=(),
    )

    assert serializer.load_observation(serializer.dump_observation(active_observation)) == active_observation
    assert (
        serializer.load_observation(serializer.dump_observation(non_active_observation))
        == non_active_observation
    )


def test_connect4_serializer_round_trips_initial_mid_game_and_terminal_states() -> None:
    serializer = Connect4Serializer()
    rules = Connect4RulesEngine()
    config = Connect4Config(rows=4, columns=4, connect_length=4)
    initial_state = rules.initial_state(config)
    mid_game_state = rules.apply_action(initial_state, 0, DropDisc(column=0)).state
    terminal_seed = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT1_DISC, SEAT1_DISC, EMPTY_CELL),
        ),
        current_seat=0,
    )
    terminal_state = rules.apply_action(terminal_seed, 0, DropDisc(column=0)).state

    for state in (initial_state, mid_game_state, terminal_state):
        rehydrated_state = serializer.load_state(serializer.dump_state(state))

        assert rehydrated_state == state
        assert isinstance(rehydrated_state.board, tuple)
        assert all(isinstance(row, tuple) for row in rehydrated_state.board)


def test_connect4_serializer_dumps_json_friendly_state_payloads() -> None:
    serializer = Connect4Serializer()
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    payload = serializer.dump_state(state)

    assert payload == {
        "board": [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 2, 0, 0],
            [1, 1, 0, 0],
        ],
        "current_seat": 0,
    }
    assert json.loads(json.dumps(payload)) == payload


def test_snapshot_envelope_rehydrates_connect4_state_semantics_with_serialized_config() -> None:
    serializer = Connect4Serializer()
    original_config = Connect4Config(rows=5, columns=5, connect_length=5)
    original_rules = Connect4RulesEngine()
    initial_state = original_rules.initial_state(original_config)
    state = initial_state

    for column in (0, 1, 0, 1, 0, 1, 0):
        seat = original_rules.current_seat(state)
        state = original_rules.apply_action(state, seat, DropDisc(column=column)).state

    envelope = SnapshotEnvelope(
        game_id="connect4",
        schema_version=1,
        config=serializer.dump_config(original_config),
        state=serializer.dump_state(state),
    )

    rehydrated_config = serializer.load_config(envelope.config)
    rehydrated_state = serializer.load_state(envelope.state)

    fresh_rules = Connect4RulesEngine(rehydrated_config)
    reused_rules = Connect4RulesEngine(Connect4Config())
    reused_rules.initial_state(rehydrated_config)

    assert fresh_rules.result(rehydrated_state) == original_rules.result(state)
    assert fresh_rules.is_terminal(rehydrated_state) == original_rules.is_terminal(state)
    assert fresh_rules.current_seat(rehydrated_state) == original_rules.current_seat(state)
    assert (
        fresh_rules.observation(rehydrated_state, fresh_rules.current_seat(rehydrated_state))
        == original_rules.observation(state, original_rules.current_seat(state))
    )
    assert reused_rules.result(rehydrated_state) == original_rules.result(state)
    assert reused_rules.legal_actions(
        rehydrated_state,
        reused_rules.current_seat(rehydrated_state),
    ) == original_rules.legal_actions(state, original_rules.current_seat(state))


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"columns": 7, "connect_length": 4}, "rows"),
        ({"rows": "6", "columns": 7, "connect_length": 4}, "rows"),
        ({"rows": 6, "columns": 7, "connect_length": 4, "extra": True}, "extra"),
    ],
)
def test_connect4_serializer_load_config_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = Connect4Serializer()

    with pytest.raises(ValidationError) as exc_info:
        serializer.load_config(payload)

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({}, "column"),
        ({"column": "3"}, "column"),
        ({"column": 1, "extra": True}, "extra"),
    ],
)
def test_connect4_serializer_load_action_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = Connect4Serializer()

    with pytest.raises(ValidationError) as exc_info:
        serializer.load_action(payload)

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"current_seat": 0}, "board"),
        ({"board": [[0, 0], [0]], "current_seat": 0}, "rectangular"),
        ({"board": [[0, 3], [0, 0]], "current_seat": 0}, "disc values"),
        ({"board": [[0, 0], [0, 0]], "current_seat": 2}, "current_seat"),
        ({"board": [[0, 0], [0, 0]], "current_seat": "0"}, "current_seat"),
        ({"board": [[0, 0], [0, 0]], "current_seat": 0, "extra": True}, "extra"),
    ],
)
def test_connect4_serializer_load_state_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = Connect4Serializer()

    with pytest.raises((ValidationError, ValueError)) as exc_info:
        serializer.load_state(payload)

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        (
            {
                "board": [[0, 0], [0, 0]],
                "current_seat": 0,
                "legal_actions": [],
            },
            "seat",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0], [0]],
                "current_seat": 0,
                "legal_actions": [],
            },
            "rectangular",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0], [0, 0]],
                "current_seat": 2,
                "legal_actions": [],
            },
            "current_seat",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0], [0, 0]],
                "current_seat": 0,
                "legal_actions": [{"column": -1}],
            },
            "column",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0], [0, 0]],
                "current_seat": 0,
                "legal_actions": [],
                "extra": True,
            },
            "extra",
        ),
    ],
)
def test_connect4_serializer_load_observation_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = Connect4Serializer()

    with pytest.raises((ValidationError, ValueError)) as exc_info:
        serializer.load_observation(payload)

    assert field_name in str(exc_info.value)


def test_connect4_serializer_dumps_json_friendly_observation_payloads() -> None:
    serializer = Connect4Serializer()
    observation = Connect4Observation(
        seat=0,
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
        legal_actions=(DropDisc(column=0), DropDisc(column=2)),
    )

    payload = serializer.dump_observation(observation)

    assert payload == {
        "seat": 0,
        "board": [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 2, 0, 0],
            [1, 1, 0, 0],
        ],
        "current_seat": 0,
        "legal_actions": [{"column": 0}, {"column": 2}],
    }
    assert json.loads(json.dumps(payload)) == payload


def test_connect4_package_exports_serializer_surface() -> None:
    assert "Connect4Serializer" in connect4_exports


def test_connect4_serializer_boundary_models_can_emit_json_schema() -> None:
    config_schema = Connect4ConfigPayload.model_json_schema()
    action_schema = DropDiscPayload.model_json_schema()
    state_schema = Connect4StatePayload.model_json_schema()
    observation_schema = Connect4ObservationPayload.model_json_schema()

    assert config_schema["title"] == "Connect4ConfigPayload"
    assert config_schema["required"] == ["rows", "columns", "connect_length"]
    assert config_schema["properties"]["rows"]["type"] == "integer"
    assert config_schema["properties"]["columns"]["type"] == "integer"
    assert config_schema["properties"]["connect_length"]["type"] == "integer"

    assert action_schema["title"] == "DropDiscPayload"
    assert action_schema["required"] == ["column"]
    assert action_schema["properties"]["column"]["type"] == "integer"
    assert action_schema["properties"]["column"]["minimum"] == 0

    assert state_schema["title"] == "Connect4StatePayload"
    assert state_schema["required"] == ["board", "current_seat"]
    assert state_schema["properties"]["board"]["type"] == "array"
    assert state_schema["properties"]["current_seat"]["type"] == "integer"

    assert observation_schema["title"] == "Connect4ObservationPayload"
    assert observation_schema["required"] == ["seat", "board", "current_seat", "legal_actions"]
    assert observation_schema["properties"]["seat"]["type"] == "integer"
    assert observation_schema["properties"]["board"]["type"] == "array"
    assert observation_schema["properties"]["current_seat"]["type"] == "integer"
    assert observation_schema["properties"]["legal_actions"]["type"] == "array"
