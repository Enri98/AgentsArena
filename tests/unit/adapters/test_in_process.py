"""Tests for the serialized in-process adapter boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from arena.adapters import (
    ADAPTER_PAYLOAD_SCHEMA_VERSION,
    ActionResponsePayload,
    ObservationRequestPayload,
    TypedPayloadPolicyAdapter,
    apply_payload_policy_turn,
    build_observation_request,
    dump_domain_error,
    load_action_response,
)
from arena.core.exceptions import IllegalAction
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    DropDisc,
)
from arena.match import start_match


@dataclass
class PayloadScriptPolicy:
    action_payloads: tuple[dict[str, int], ...]
    requests: list[ObservationRequestPayload] = field(default_factory=list)
    index: int = 0

    def select_action(self, request: ObservationRequestPayload) -> ActionResponsePayload:
        self.requests.append(request)
        action = self.action_payloads[self.index]
        self.index += 1
        return ActionResponsePayload(
            game_id=request.game_id,
            schema_version=request.schema_version,
            seat=request.seat,
            action=action,
        )


@dataclass
class TypedRecordingAgent:
    actions: tuple[DropDisc, ...]
    observations: list[Connect4Observation] = field(default_factory=list)
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        self.observations.append(observation)
        action = self.actions[self.index]
        self.index += 1
        return action


@dataclass
class WrongActionAgent:
    observations: list[Connect4Observation] = field(default_factory=list)

    def select_action(self, observation: Connect4Observation) -> object:
        self.observations.append(observation)
        return object()


def test_build_observation_request_uses_active_seat_and_game_serializer() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config())

    request = build_observation_request(match)

    assert request.game_id == CONNECT4_GAME_ID
    assert request.schema_version == ADAPTER_PAYLOAD_SCHEMA_VERSION
    assert request.seat == 0
    assert request.observation["seat"] == 0
    assert request.observation["current_seat"] == 0
    assert request.observation["legal_actions"] == [
        {"column": column} for column in range(match.config.columns)
    ]


def test_load_action_response_rehydrates_action_through_game_serializer() -> None:
    response = ActionResponsePayload(
        game_id=CONNECT4_GAME_ID,
        schema_version=ADAPTER_PAYLOAD_SCHEMA_VERSION,
        seat=0,
        action={"column": 2},
    )

    action = load_action_response(Connect4GameDefinition, response)

    assert action == DropDisc(column=2)


def test_apply_payload_policy_turn_applies_one_serialized_policy_action() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config())
    policy = PayloadScriptPolicy(action_payloads=({"column": 0},))

    next_match = apply_payload_policy_turn(match, policy)

    assert next_match is not match
    assert len(policy.requests) == 1
    assert policy.requests[0].observation["seat"] == 0
    assert next_match.turns[0].seat == 0
    assert next_match.turns[0].action == DropDisc(column=0)
    assert next_match.state.current_seat == 1


def test_typed_payload_policy_adapter_loads_observation_and_dumps_action() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config())
    request = build_observation_request(match)
    agent = TypedRecordingAgent(actions=(DropDisc(column=2),))
    adapter = TypedPayloadPolicyAdapter(Connect4GameDefinition, agent)

    response = adapter.select_action(request)

    assert len(agent.observations) == 1
    assert agent.observations[0] == match.rules_engine.observation(match.state, 0)
    assert response == ActionResponsePayload(
        game_id=CONNECT4_GAME_ID,
        schema_version=ADAPTER_PAYLOAD_SCHEMA_VERSION,
        seat=0,
        action={"column": 2},
    )


def test_typed_payload_policy_adapter_can_drive_one_payload_policy_turn() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config())
    agent = TypedRecordingAgent(actions=(DropDisc(column=0),))
    adapter = TypedPayloadPolicyAdapter(Connect4GameDefinition, agent)

    next_match = apply_payload_policy_turn(match, adapter)

    assert len(agent.observations) == 1
    assert next_match.turns[0].seat == 0
    assert next_match.turns[0].action == DropDisc(column=0)
    assert next_match.state.current_seat == 1


def test_typed_payload_policy_adapter_rejects_foreign_request_and_schema_version() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config())
    request = build_observation_request(match)
    agent = TypedRecordingAgent(actions=(DropDisc(column=0),))
    adapter = TypedPayloadPolicyAdapter(Connect4GameDefinition, agent)

    foreign_game = request.model_copy(update={"game_id": "other-game"})
    wrong_schema = request.model_copy(
        update={"schema_version": ADAPTER_PAYLOAD_SCHEMA_VERSION + 1}
    )

    with pytest.raises(ValueError, match="game_id"):
        adapter.select_action(foreign_game)

    with pytest.raises(ValueError, match="schema_version"):
        adapter.select_action(wrong_schema)

    assert agent.observations == []


def test_typed_payload_policy_adapter_surfaces_wrong_action_type_from_serializer() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config())
    adapter = TypedPayloadPolicyAdapter(Connect4GameDefinition, WrongActionAgent())

    with pytest.raises(TypeError, match="Expected DropDisc"):
        apply_payload_policy_turn(match, adapter)


def test_apply_payload_policy_turn_surfaces_domain_errors_without_translation() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config())
    policy = PayloadScriptPolicy(action_payloads=({"column": match.config.columns},))

    with pytest.raises(IllegalAction) as exc_info:
        apply_payload_policy_turn(match, policy)

    payload = dump_domain_error(exc_info.value)

    assert payload.code == "illegal_action"
    assert payload.message == "The selected column is outside the board."
    assert payload.details == {"column": match.config.columns}


def test_action_response_rejects_foreign_game_and_schema_version() -> None:
    foreign_game = ActionResponsePayload(
        game_id="other-game",
        schema_version=ADAPTER_PAYLOAD_SCHEMA_VERSION,
        seat=0,
        action={"column": 0},
    )
    wrong_schema = ActionResponsePayload(
        game_id=CONNECT4_GAME_ID,
        schema_version=ADAPTER_PAYLOAD_SCHEMA_VERSION + 1,
        seat=0,
        action={"column": 0},
    )

    with pytest.raises(ValueError, match="game_id"):
        load_action_response(Connect4GameDefinition, foreign_game)

    with pytest.raises(ValueError, match="schema_version"):
        load_action_response(Connect4GameDefinition, wrong_schema)
