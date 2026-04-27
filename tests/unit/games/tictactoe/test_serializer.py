"""Tests for the Tic-Tac-Toe serializer boundary."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from arena.core.serializer import Serializer, SnapshotEnvelope
from arena.games.tictactoe import (
    EMPTY_CELL,
    SEAT0_MARK,
    SEAT1_MARK,
    PlaceMark,
    TicTacToeConfig,
    TicTacToeObservation,
    TicTacToeRulesEngine,
    TicTacToeSerializer,
    TicTacToeState,
)
from arena.games.tictactoe import __all__ as tictactoe_exports
from arena.games.tictactoe.serializer import (
    PlaceMarkPayload,
    TicTacToeConfigPayload,
    TicTacToeObservationPayload,
    TicTacToeStatePayload,
)


def test_tictactoe_serializer_is_importable_and_satisfies_the_shared_contract() -> None:
    serializer = TicTacToeSerializer()

    assert TicTacToeSerializer.__name__ == "TicTacToeSerializer"
    assert isinstance(serializer, Serializer)


def test_tictactoe_serializer_round_trips_config() -> None:
    serializer = TicTacToeSerializer()

    config = TicTacToeConfig()

    assert serializer.load_config(serializer.dump_config(config)) == config


def test_tictactoe_serializer_dumps_json_friendly_config_payloads() -> None:
    serializer = TicTacToeSerializer()
    payload = serializer.dump_config(TicTacToeConfig())

    assert payload == {"rows": 3, "columns": 3, "connect_length": 3}
    assert json.loads(json.dumps(payload)) == payload


def test_tictactoe_serializer_round_trips_boundary_place_mark_actions() -> None:
    serializer = TicTacToeSerializer()

    for action in (PlaceMark(row=0, column=0), PlaceMark(row=2, column=1)):
        assert serializer.load_action(serializer.dump_action(action)) == action


def test_tictactoe_serializer_dumps_json_friendly_action_payloads() -> None:
    serializer = TicTacToeSerializer()
    payload = serializer.dump_action(PlaceMark(row=1, column=2))

    assert payload == {"row": 1, "column": 2}
    assert json.loads(json.dumps(payload)) == payload


def test_tictactoe_serializer_round_trips_active_and_non_active_observations() -> None:
    serializer = TicTacToeSerializer()
    board = (
        (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
        (SEAT0_MARK, SEAT0_MARK, EMPTY_CELL),
    )

    active_observation = TicTacToeObservation(
        seat=0,
        board=board,
        current_seat=0,
        legal_actions=(
            PlaceMark(row=0, column=0),
            PlaceMark(row=0, column=1),
            PlaceMark(row=0, column=2),
        ),
    )
    non_active_observation = TicTacToeObservation(
        seat=1,
        board=board,
        current_seat=0,
        legal_actions=(),
    )

    assert (
        serializer.load_observation(serializer.dump_observation(active_observation))
        == active_observation
    )
    assert (
        serializer.load_observation(serializer.dump_observation(non_active_observation))
        == non_active_observation
    )


def test_tictactoe_serializer_round_trips_initial_mid_game_and_terminal_states() -> None:
    serializer = TicTacToeSerializer()
    rules = TicTacToeRulesEngine()
    config = TicTacToeConfig()
    initial_state = rules.initial_state(config)
    mid_game_state = rules.apply_action(initial_state, 0, PlaceMark(row=0, column=0)).state
    terminal_seed = TicTacToeState(
        board=(
            (SEAT0_MARK, SEAT0_MARK, EMPTY_CELL),
            (SEAT1_MARK, SEAT1_MARK, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )
    terminal_state = rules.apply_action(terminal_seed, 0, PlaceMark(row=0, column=2)).state

    for state in (initial_state, mid_game_state, terminal_state):
        rehydrated_state = serializer.load_state(serializer.dump_state(state))

        assert rehydrated_state == state
        assert isinstance(rehydrated_state.board, tuple)
        assert all(isinstance(row, tuple) for row in rehydrated_state.board)


def test_tictactoe_serializer_dumps_json_friendly_state_payloads() -> None:
    serializer = TicTacToeSerializer()
    state = TicTacToeState(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
            (SEAT0_MARK, SEAT0_MARK, EMPTY_CELL),
        ),
        current_seat=0,
    )

    payload = serializer.dump_state(state)

    assert payload == {
        "board": [
            [0, 0, 0],
            [0, 2, 0],
            [1, 1, 0],
        ],
        "current_seat": 0,
    }
    assert json.loads(json.dumps(payload)) == payload


def test_snapshot_envelope_rehydrates_tictactoe_state_semantics_with_serialized_config() -> None:
    serializer = TicTacToeSerializer()
    original_config = TicTacToeConfig()
    original_rules = TicTacToeRulesEngine()
    initial_state = original_rules.initial_state(original_config)
    state = initial_state

    for row, column in ((0, 0), (1, 1), (0, 1), (2, 2), (0, 2)):
        seat = original_rules.current_seat(state)
        state = original_rules.apply_action(state, seat, PlaceMark(row=row, column=column)).state

    envelope = SnapshotEnvelope(
        game_id="tictactoe",
        schema_version=1,
        config=serializer.dump_config(original_config),
        state=serializer.dump_state(state),
    )

    rehydrated_config = serializer.load_config(envelope.config)
    rehydrated_state = serializer.load_state(envelope.state)

    fresh_rules = TicTacToeRulesEngine(rehydrated_config)

    assert fresh_rules.result(rehydrated_state) == original_rules.result(state)
    assert fresh_rules.is_terminal(rehydrated_state) == original_rules.is_terminal(state)
    assert fresh_rules.current_seat(rehydrated_state) == original_rules.current_seat(state)
    assert fresh_rules.observation(
        rehydrated_state, fresh_rules.current_seat(rehydrated_state)
    ) == original_rules.observation(state, original_rules.current_seat(state))


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"rows": 4, "columns": 3, "connect_length": 3}, "fixed"),
        ({"rows": "3", "columns": 3, "connect_length": 3}, "rows"),
        ({"rows": 3, "columns": 3, "connect_length": 3, "extra": True}, "extra"),
    ],
)
def test_tictactoe_serializer_load_config_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = TicTacToeSerializer()

    with pytest.raises(ValidationError) as exc_info:
        serializer.load_config(payload)

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({}, "row"),
        ({"row": "0", "column": 0}, "row"),
        ({"row": 0, "column": 0, "extra": True}, "extra"),
    ],
)
def test_tictactoe_serializer_load_action_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = TicTacToeSerializer()

    with pytest.raises(ValidationError) as exc_info:
        serializer.load_action(payload)

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"current_seat": 0}, "board"),
        ({"board": [[0, 0, 0], [0, 0], [0, 0, 0]], "current_seat": 0}, "rectangular"),
        ({"board": [[0, 4, 0], [0, 0, 0], [0, 0, 0]], "current_seat": 0}, "mark values"),
        ({"board": [[0, 0, 0], [0, 0, 0], [0, 0, 0]], "current_seat": 2}, "current_seat"),
        ({"board": [[0, 0, 0], [0, 0, 0], [0, 0, 0]], "current_seat": 0, "extra": True}, "extra"),
    ],
)
def test_tictactoe_serializer_load_state_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = TicTacToeSerializer()

    with pytest.raises((ValidationError, ValueError)) as exc_info:
        serializer.load_state(payload)

    assert field_name in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        (
            {
                "board": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
                "current_seat": 0,
                "legal_actions": [],
            },
            "seat",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0, 0], [0, 0], [0, 0, 0]],
                "current_seat": 0,
                "legal_actions": [],
            },
            "rectangular",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0, 0], [0, 0, 0], [0, 4, 0]],
                "current_seat": 0,
                "legal_actions": [],
            },
            "mark values",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
                "current_seat": 2,
                "legal_actions": [],
            },
            "current_seat",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
                "current_seat": 0,
                "legal_actions": [{"row": -1, "column": 0}],
            },
            "row",
        ),
        (
            {
                "seat": 0,
                "board": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
                "current_seat": 0,
                "legal_actions": [],
                "extra": True,
            },
            "extra",
        ),
    ],
)
def test_tictactoe_serializer_load_observation_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    serializer = TicTacToeSerializer()

    with pytest.raises((ValidationError, ValueError)) as exc_info:
        serializer.load_observation(payload)

    assert field_name in str(exc_info.value)


def test_tictactoe_serializer_dumps_json_friendly_observation_payloads() -> None:
    serializer = TicTacToeSerializer()
    observation = TicTacToeObservation(
        seat=0,
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
            (SEAT0_MARK, SEAT0_MARK, EMPTY_CELL),
        ),
        current_seat=0,
        legal_actions=(PlaceMark(row=0, column=0), PlaceMark(row=2, column=2)),
    )

    payload = serializer.dump_observation(observation)

    assert payload == {
        "seat": 0,
        "board": [
            [0, 0, 0],
            [0, 2, 0],
            [1, 1, 0],
        ],
        "current_seat": 0,
        "legal_actions": [{"row": 0, "column": 0}, {"row": 2, "column": 2}],
    }
    assert json.loads(json.dumps(payload)) == payload


def test_tictactoe_package_exports_serializer_surface() -> None:
    assert "TicTacToeSerializer" in tictactoe_exports


def test_tictactoe_serializer_boundary_models_can_emit_json_schema() -> None:
    config_schema = TicTacToeConfigPayload.model_json_schema()
    action_schema = PlaceMarkPayload.model_json_schema()
    state_schema = TicTacToeStatePayload.model_json_schema()
    observation_schema = TicTacToeObservationPayload.model_json_schema()

    assert config_schema["title"] == "TicTacToeConfigPayload"
    assert config_schema["properties"]["rows"]["default"] == 3
    assert config_schema["properties"]["columns"]["default"] == 3
    assert config_schema["properties"]["connect_length"]["default"] == 3
    assert action_schema["title"] == "PlaceMarkPayload"
    assert action_schema["required"] == ["row", "column"]
    assert state_schema["title"] == "TicTacToeStatePayload"
    assert state_schema["required"] == ["board", "current_seat"]
    assert observation_schema["title"] == "TicTacToeObservationPayload"
    assert observation_schema["required"] == ["seat", "board", "current_seat", "legal_actions"]
