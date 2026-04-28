"""Tests for TicTacToePromptBuilder prompt rendering and response parsing."""

from __future__ import annotations

import json
from collections import deque
from typing import Any

from arena.agents.ollama.agent import OllamaAgent
from arena.agents.ollama.tictactoe import TicTacToePromptBuilder
from arena.games.tictactoe import TicTacToeConfig, TicTacToeGameDefinition
from arena.games.tictactoe.actions import PlaceMark
from arena.match.local_match import start_match


def _make_observation() -> Any:
    definition = TicTacToeGameDefinition
    config = TicTacToeConfig()
    match = start_match(definition, config)
    state = match.state
    seat = definition.rules_engine.current_seat(state)
    return definition.rules_engine.observation(state, seat)


class _StubClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses: deque[str] = deque(responses)

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        format_spec: Any,
        seed: int,
        temperature: float,
    ) -> dict[str, Any]:
        content = self._responses.popleft()
        return {"message": {"content": content}}


def test_build_messages_returns_system_and_user() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_system_message_is_deterministic() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    m1 = builder.build_messages(obs)
    m2 = builder.build_messages(obs)
    assert m1[0]["content"] == m2[0]["content"]
    assert m1[1]["content"] == m2[1]["content"]


def test_user_message_contains_board() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Board:" in user


def test_user_message_contains_legal_keys() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Legal keys:" in user


def test_user_message_contains_snapshot() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Snapshot:" in user
    assert "current_seat" in user


def test_retry_feedback_injected_when_present() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs, retry_feedback=("bad key",))
    user = messages[1]["content"]
    assert "Previous attempts were rejected:" in user
    assert "bad key" in user


def test_no_feedback_section_without_feedback() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Previous attempts were rejected" not in user


def test_parse_response_legal_key() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    result = builder.parse_response(json.dumps({"key": 1}), obs)
    assert isinstance(result, PlaceMark)
    assert result == PlaceMark(row=0, column=0)


def test_parse_response_out_of_range_key_returns_none() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    result = builder.parse_response(json.dumps({"key": 99}), obs)
    assert result is None


def test_parse_response_malformed_returns_none() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    result = builder.parse_response("not json at all", obs)
    assert result is None


def test_parse_response_missing_key_returns_none() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    result = builder.parse_response(json.dumps({}), obs)
    assert result is None


def test_parse_response_non_int_key_returns_none() -> None:
    builder = TicTacToePromptBuilder()
    obs = _make_observation()
    result = builder.parse_response(json.dumps({"key": "1"}), obs)
    assert result is None


def test_integration_stub_client_returns_legal_action() -> None:
    obs = _make_observation()
    client = _StubClient([json.dumps({"key": 1})])
    builder = TicTacToePromptBuilder()
    agent = OllamaAgent(client=client, model="x", prompt_builder=builder)
    result = agent.select_action(obs)
    assert result == PlaceMark(row=0, column=0)


def test_format_spec_has_key_with_range() -> None:
    builder = TicTacToePromptBuilder()
    spec = builder.format_spec()
    assert spec["type"] == "object"
    assert "key" in spec["properties"]
    assert spec["properties"]["key"]["minimum"] == 1
    assert spec["properties"]["key"]["maximum"] == 9
