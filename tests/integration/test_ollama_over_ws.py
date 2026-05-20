"""Phase 31: OllamaAgent wired through arena.sdk against a real arena.server.

No real Ollama daemon is required: each OllamaAgent is given a MagicMock client
that returns deterministic JSON so the match completes in a fixed number of turns.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import httpx

from arena.agents.ollama import OllamaAgent, run_remote_seat
from arena.agents.ollama.client import OllamaClient
from arena.agents.ollama.connect4 import Connect4PromptBuilder
from arena.cli.remote import make_typed_agent_choose
from arena.games import build_default_registry
from arena.games.connect4 import Connect4GameDefinition
from arena.runtime.payloads import validate_runtime_transcript
from arena.sdk import connect
from tests.integration.conftest import RunningServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_match(http_base: str, game_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"game_id": game_id, **extra}
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _build_stub_agent(column: int) -> OllamaAgent:
    """Build an OllamaAgent whose HTTP client is a MagicMock returning column."""
    client = MagicMock(spec=OllamaClient)
    client.chat.return_value = {
        "message": {"content": json.dumps({"thought": "auto", "column": column})}
    }
    return OllamaAgent(
        client=client,
        model="stub-model",
        prompt_builder=Connect4PromptBuilder(),
        max_retries=3,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ollama_over_ws_completes_match(running_server: RunningServer) -> None:
    """OllamaAgent wired via make_typed_agent_choose drives a full Connect 4 match."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "ollama-seat0"}, {"label": "ollama-seat1"}],
        )

        # Seat 0 always drops column 0; seat 1 always drops column 1.
        # With default 6x7 board seat 0 wins by vertical connect-4 after 7 turns.
        agent0 = _build_stub_agent(column=0)
        agent1 = _build_stub_agent(column=1)

        choose0 = make_typed_agent_choose(agent0, Connect4GameDefinition)
        choose1 = make_typed_agent_choose(agent1, Connect4GameDefinition)

        (result0, transcript0), (result1, transcript1) = await asyncio.gather(
            connect(match["seat_0_url"], 0, choose0),
            connect(match["seat_1_url"], 1, choose1),
        )

        assert transcript0 is not None
        assert transcript1 is not None
        assert transcript0.lifecycle == "finished"
        assert transcript1.lifecycle == "finished"

        # Transcript must pass full validation contract.
        registry = build_default_registry()
        definition = registry.get("connect4")
        loaded = validate_runtime_transcript(
            definition, transcript0.model_dump(mode="json")
        )
        assert loaded is not None

    asyncio.run(run())


def test_make_typed_agent_choose_action_shape(running_server: RunningServer) -> None:
    """make_typed_agent_choose() sends correctly shaped action dicts to the server."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "a"}, {"label": "b"}],
        )

        # Seat 0 plays column 2, seat 1 plays column 4; seat 0 wins vertically.
        agent0 = _build_stub_agent(column=2)
        agent1 = _build_stub_agent(column=4)

        choose0 = make_typed_agent_choose(agent0, Connect4GameDefinition)
        choose1 = make_typed_agent_choose(agent1, Connect4GameDefinition)

        (result0, transcript0), _ = await asyncio.gather(
            connect(match["seat_0_url"], 0, choose0),
            connect(match["seat_1_url"], 1, choose1),
        )

        assert transcript0.lifecycle == "finished"
        # Verify each turn record carries a 'column' action key (Connect 4 action shape).
        match_txn = transcript0.match_transcript or {}
        for turn in match_txn.get("turns", []):
            action = turn.get("action", {})
            assert "column" in action, f"Expected 'column' key in action {action!r}"

    asyncio.run(run())


def _stub_client_returning(column: int) -> Any:
    """Build a MagicMock OllamaClient that always answers with the given column."""
    client = MagicMock(spec=OllamaClient)
    client.chat.return_value = {
        "message": {"content": json.dumps({"thought": "auto", "column": column})}
    }
    return client


def test_run_remote_seat_drives_connect4_match(running_server: RunningServer) -> None:
    """run_remote_seat() bundles the Ollama+SDK wiring into a single call."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "rs-0"}, {"label": "rs-1"}],
        )

        retry_sink_0: list[tuple[int, str]] = []
        retry_sink_1: list[tuple[int, str]] = []

        (result0, transcript0), (result1, transcript1) = await asyncio.gather(
            run_remote_seat(
                server_url=match["seat_0_url"],
                seat=0,
                game_id="connect4",
                model="stub",
                client=_stub_client_returning(0),
                retry_sink=retry_sink_0,
            ),
            run_remote_seat(
                server_url=match["seat_1_url"],
                seat=1,
                game_id="connect4",
                model="stub",
                client=_stub_client_returning(1),
                retry_sink=retry_sink_1,
            ),
        )

        assert transcript0.lifecycle == "finished"
        assert transcript1.lifecycle == "finished"

        registry = build_default_registry()
        loaded = validate_runtime_transcript(
            registry.get("connect4"), transcript0.model_dump(mode="json")
        )
        assert loaded is not None

    asyncio.run(run())


def test_run_remote_seat_rejects_unknown_game() -> None:
    """run_remote_seat() raises ValueError when game_id is not supported."""

    import pytest

    async def run() -> None:
        with pytest.raises(ValueError, match="Unsupported game_id"):
            await run_remote_seat(
                server_url="ws://example/invalid",
                seat=0,
                game_id="chess",
                model="stub",
                client=_stub_client_returning(0),
            )

    asyncio.run(run())
