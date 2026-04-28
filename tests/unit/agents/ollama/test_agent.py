"""Tests for OllamaAgent retry loop using stub transport and stub PromptBuilder."""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest

from arena.agents.ollama.agent import OllamaAgent
from arena.agents.ollama.exceptions import OllamaIllegalActionError


class _FakeAction:
    def __init__(self, value: int) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _FakeAction) and other.value == self.value

    def __repr__(self) -> str:
        return f"FakeAction({self.value})"


class _FakeObservation:
    def __init__(self, legal: list[int]) -> None:
        self.legal_actions = [_FakeAction(v) for v in legal]


class _StubPromptBuilder:
    def build_messages(
        self, observation: Any, retry_feedback: tuple[str, ...] = ()
    ) -> list[dict[str, str]]:
        return [{"role": "user", "content": "pick"}]

    def parse_response(self, content: str, observation: Any) -> Any | None:
        try:
            value = int(content.strip())
            return _FakeAction(value)
        except ValueError:
            return None

    def format_spec(self) -> dict[str, Any]:
        return {}

    def describe_invalid(self, raw_content: str) -> str:
        return f"could not parse: {raw_content!r}"


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


def test_legal_first_try_returns_action_callback_never_fires() -> None:
    fired: list[tuple[int, str]] = []
    client = _StubClient(["0"])
    agent = OllamaAgent(
        client=client,
        model="x",
        prompt_builder=_StubPromptBuilder(),
        max_retries=3,
        retry_callback=lambda attempt, reason: fired.append((attempt, reason)),
    )
    obs = _FakeObservation([0, 1, 2])
    result = agent.select_action(obs)
    assert result == _FakeAction(0)
    assert fired == []


def test_illegal_then_legal_callback_fires_once() -> None:
    fired: list[tuple[int, str]] = []
    client = _StubClient(["99", "1"])
    agent = OllamaAgent(
        client=client,
        model="x",
        prompt_builder=_StubPromptBuilder(),
        max_retries=3,
        retry_callback=lambda attempt, reason: fired.append((attempt, reason)),
    )
    obs = _FakeObservation([1, 2])
    result = agent.select_action(obs)
    assert result == _FakeAction(1)
    assert len(fired) == 1
    assert fired[0][0] == 1


def test_exhausted_retries_raises_illegal_action_error() -> None:
    fired: list[tuple[int, str]] = []
    client = _StubClient(["99", "99", "99", "99"])
    agent = OllamaAgent(
        client=client,
        model="mymodel",
        prompt_builder=_StubPromptBuilder(),
        max_retries=3,
        retry_callback=lambda attempt, reason: fired.append((attempt, reason)),
    )
    obs = _FakeObservation([0, 1])
    with pytest.raises(OllamaIllegalActionError) as exc_info:
        agent.select_action(obs)

    err = exc_info.value
    assert err.model == "mymodel"
    assert err.attempts == 4
    assert "mymodel" in str(err)
    assert len(fired) == 3


def test_malformed_json_retried_callback_fires() -> None:
    fired: list[tuple[int, str]] = []
    client = _StubClient(["not_a_number", "2"])
    agent = OllamaAgent(
        client=client,
        model="x",
        prompt_builder=_StubPromptBuilder(),
        max_retries=3,
        retry_callback=lambda attempt, reason: fired.append((attempt, reason)),
    )
    obs = _FakeObservation([2])
    result = agent.select_action(obs)
    assert result == _FakeAction(2)
    assert len(fired) == 1
    assert "could not parse" in fired[0][1]


def test_callback_not_fired_on_final_failed_attempt() -> None:
    fired: list[int] = []
    client = _StubClient(["99"] * 4)
    agent = OllamaAgent(
        client=client,
        model="x",
        prompt_builder=_StubPromptBuilder(),
        max_retries=3,
        retry_callback=lambda attempt, reason: fired.append(attempt),
    )
    obs = _FakeObservation([0])
    with pytest.raises(OllamaIllegalActionError):
        agent.select_action(obs)
    assert fired == [1, 2, 3]


def test_no_callback_configured_still_raises() -> None:
    client = _StubClient(["99"] * 2)
    agent = OllamaAgent(
        client=client,
        model="m",
        prompt_builder=_StubPromptBuilder(),
        max_retries=1,
        retry_callback=None,
    )
    obs = _FakeObservation([0])
    with pytest.raises(OllamaIllegalActionError):
        agent.select_action(obs)


def test_illegal_action_error_message_contains_model_and_last_attempt() -> None:
    client = _StubClient(["99", "99"])
    agent = OllamaAgent(
        client=client,
        model="testmodel",
        prompt_builder=_StubPromptBuilder(),
        max_retries=1,
    )
    obs = _FakeObservation([0])
    with pytest.raises(OllamaIllegalActionError) as exc_info:
        agent.select_action(obs)
    err_str = str(exc_info.value)
    assert "testmodel" in err_str
    assert exc_info.value.last_attempt != ""
