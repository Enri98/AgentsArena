"""Tests for PolicyRetried runtime event emission via play_match retry_sink."""

from __future__ import annotations

import json
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

from arena.adapters.in_process import TypedPayloadPolicyAdapter
from arena.agents.ollama.agent import OllamaAgent
from arena.agents.ollama.connect4 import Connect4PromptBuilder
from arena.cli.play import play_match
from arena.games.connect4 import Connect4Config, Connect4GameDefinition
from arena.runtime import PlayerRecord


class _QueueClient:
    """Stub OllamaClient that returns responses from a per-model queue."""

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


class _CyclingClient:
    """Stub client that cycles through columns 0-3 to stay legal on a 4x4 board."""

    def __init__(self) -> None:
        self._turn = 0

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        format_spec: Any,
        seed: int,
        temperature: float,
    ) -> dict[str, Any]:
        col = self._turn % 4
        self._turn += 1
        return {"message": {"content": json.dumps({"column": col})}}


def _legal_column_responses(n: int) -> list[str]:
    return [json.dumps({"column": i % 4}) for i in range(n)]


def test_policy_retried_event_in_transcript_when_forced_retry() -> None:
    definition = Connect4GameDefinition
    config = Connect4Config(rows=4, columns=4, connect_length=4)

    retry_sink: dict[int, list[tuple[int, str]]] = {}

    seat0_entries: list[tuple[int, str]] = []
    retry_sink[0] = seat0_entries

    seat1_entries: list[tuple[int, str]] = []
    retry_sink[1] = seat1_entries

    illegal_then_legal = [
        json.dumps({"column": 99}),
        json.dumps({"column": 0}),
    ]
    client0 = _QueueClient(illegal_then_legal + _legal_column_responses(30))
    client1 = _QueueClient(_legal_column_responses(30))

    def _cb0(attempt: int, reason: str) -> None:
        seat0_entries.append((attempt, reason))

    def _cb1(attempt: int, reason: str) -> None:
        seat1_entries.append((attempt, reason))

    agent0 = OllamaAgent(
        client=client0,
        model="model-a",
        prompt_builder=Connect4PromptBuilder(),
        max_retries=3,
        retry_callback=_cb0,
    )
    agent1 = OllamaAgent(
        client=client1,
        model="model-b",
        prompt_builder=Connect4PromptBuilder(),
        max_retries=3,
        retry_callback=_cb1,
    )

    players = (
        PlayerRecord(player_id="p0", seat=0),
        PlayerRecord(player_id="p1", seat=1),
    )
    policies = {
        0: TypedPayloadPolicyAdapter(definition, agent0),
        1: TypedPayloadPolicyAdapter(definition, agent1),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        play_match(
            definition,
            config,
            players,
            policies,
            out_dir=tmpdir,
            retry_sink=retry_sink,
        )

        transcript_path = Path(tmpdir) / "transcript.json"
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    events = transcript["events"]
    retried_events = [e for e in events if e["event_type"] == "PolicyRetried"]
    assert len(retried_events) >= 1

    first = retried_events[0]
    assert first["event_scope"] == "runtime"
    assert first["payload"]["seat"] == 0
    assert first["payload"]["attempt"] == 1
    assert isinstance(first["payload"]["reason_summary"], str)


def test_no_policy_retried_event_when_all_responses_legal() -> None:
    definition = Connect4GameDefinition
    config = Connect4Config(rows=4, columns=4, connect_length=4)

    retry_sink: dict[int, list[tuple[int, str]]] = {}
    seat0_entries: list[tuple[int, str]] = []
    retry_sink[0] = seat0_entries
    seat1_entries: list[tuple[int, str]] = []
    retry_sink[1] = seat1_entries

    client0 = _CyclingClient()
    client1 = _CyclingClient()

    agent0 = OllamaAgent(
        client=client0,
        model="model-a",
        prompt_builder=Connect4PromptBuilder(),
        retry_callback=lambda a, r: seat0_entries.append((a, r)),
    )
    agent1 = OllamaAgent(
        client=client1,
        model="model-b",
        prompt_builder=Connect4PromptBuilder(),
        retry_callback=lambda a, r: seat1_entries.append((a, r)),
    )

    players = (
        PlayerRecord(player_id="p0", seat=0),
        PlayerRecord(player_id="p1", seat=1),
    )
    policies = {
        0: TypedPayloadPolicyAdapter(definition, agent0),
        1: TypedPayloadPolicyAdapter(definition, agent1),
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        play_match(
            definition,
            config,
            players,
            policies,
            out_dir=tmpdir,
            retry_sink=retry_sink,
        )
        transcript = json.loads(
            (Path(tmpdir) / "transcript.json").read_text(encoding="utf-8")
        )

    retried_events = [e for e in transcript["events"] if e["event_type"] == "PolicyRetried"]
    assert retried_events == []


def test_smoke_example_run_with_stub_client() -> None:
    import examples.run_ollama_vs_ollama as example_mod

    def _factory(host: str) -> Any:
        return _CyclingClient()

    with tempfile.TemporaryDirectory() as tmpdir:
        result = example_mod.run(tmpdir, host="http://localhost:11434", client_factory=_factory)
        assert result in (0, 1)
        assert (Path(tmpdir) / "status.json").exists()
        assert (Path(tmpdir) / "transcript.json").exists()
        transcript = json.loads(
            (Path(tmpdir) / "transcript.json").read_text(encoding="utf-8")
        )
    assert "events" in transcript
