"""Tests for Connect4PromptBuilder prompt rendering and response parsing."""

from __future__ import annotations

import json
from collections import deque
from typing import Any

from arena.agents.ollama.agent import OllamaAgent
from arena.agents.ollama.connect4 import Connect4PromptBuilder
from arena.games.connect4 import Connect4Config, Connect4GameDefinition, DropDisc
from arena.match.local_match import start_match


def _make_observation() -> Any:
    definition = Connect4GameDefinition
    config = Connect4Config(rows=4, columns=4, connect_length=4)
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
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_system_message_is_deterministic() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    m1 = builder.build_messages(obs)
    m2 = builder.build_messages(obs)
    assert m1[0]["content"] == m2[0]["content"]
    assert m1[1]["content"] == m2[1]["content"]


def test_user_message_contains_board() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Board" in user


def test_user_message_contains_legal_columns() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Legal columns" in user
    for action in obs.legal_actions:
        assert str(action.column) in user


def test_user_message_contains_symbol_grid() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Board as nested rows of symbols" in user


def test_user_message_contains_seat_identity() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    seat = obs.current_seat
    assert f"seat {seat}" in user
    assert "X" in user
    assert "O" in user


def test_user_message_contains_thought_instruction() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "thought" in user
    assert "column" in user


def test_system_message_contains_strategy_hints() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    system = messages[0]["content"]
    assert "center" in system
    assert "block" in system
    assert "win" in system.lower()


def test_retry_feedback_injected_when_present() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs, retry_feedback=("bad move",))
    user = messages[1]["content"]
    assert "Previous attempts were rejected:" in user
    assert "bad move" in user


def test_no_retry_feedback_section_without_feedback() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "Previous attempts were rejected" not in user


def test_parse_response_legal_column_with_thought() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    legal_col = obs.legal_actions[0].column
    result = builder.parse_response(
        json.dumps({"thought": "play center", "column": legal_col}), obs
    )
    assert result == DropDisc(column=legal_col)


def test_parse_response_legal_column_without_thought() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    legal_col = obs.legal_actions[0].column
    result = builder.parse_response(json.dumps({"column": legal_col}), obs)
    assert result == DropDisc(column=legal_col)


def test_parse_response_out_of_range_returns_none() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    result = builder.parse_response(json.dumps({"thought": "x", "column": 999}), obs)
    assert result is None


def test_parse_response_malformed_returns_none() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    result = builder.parse_response("abc not json", obs)
    assert result is None


def test_parse_response_missing_column_returns_none() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    result = builder.parse_response(json.dumps({"thought": "thinking"}), obs)
    assert result is None


def test_parse_response_non_int_column_returns_none() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    result = builder.parse_response(json.dumps({"thought": "x", "column": "0"}), obs)
    assert result is None


def test_integration_stub_client_returns_legal_action() -> None:
    obs = _make_observation()
    legal_col = obs.legal_actions[0].column
    client = _StubClient([json.dumps({"thought": "play here", "column": legal_col})])
    builder = Connect4PromptBuilder()
    agent = OllamaAgent(client=client, model="x", prompt_builder=builder)
    result = agent.select_action(obs)
    assert result == DropDisc(column=legal_col)


def test_format_spec_is_json_schema_object() -> None:
    builder = Connect4PromptBuilder()
    spec = builder.format_spec()
    assert spec["type"] == "object"
    assert "column" in spec["properties"]
    assert "thought" in spec["properties"]
    assert "thought" in spec["required"]
    assert "column" in spec["required"]


def test_board_in_prompt_has_no_ansi_escapes() -> None:
    builder = Connect4PromptBuilder()
    obs = _make_observation()
    messages = builder.build_messages(obs)
    user = messages[1]["content"]
    assert "\x1b[" not in user
