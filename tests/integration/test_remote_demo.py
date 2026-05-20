"""Phase 34 Slice 7: integration tests for run_remote_seat() end-to-end.

Three tests:
1. Happy-path Connect 4 match via run_remote_seat with stub OllamaClient.
2. Abort (peer_disconnected) when seat 1 closes its WS mid-match.
3. Nim smoke test using a custom prompt_builder that always picks the first legal action.

No real Ollama daemon is required.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import httpx

from arena.agents.ollama import run_remote_seat
from arena.agents.ollama.client import OllamaClient
from arena.games import build_default_registry
from arena.runtime.payloads import validate_runtime_transcript
from arena.sdk import Session
from arena.sdk.errors import MatchAbortedError
from tests.integration.conftest import RunningServer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_match(http_base: str, game_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"game_id": game_id, **extra}
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _stub_client_returning(column: int) -> Any:
    """MagicMock OllamaClient that always answers with the given Connect 4 column."""
    client = MagicMock(spec=OllamaClient)
    client.chat.return_value = {
        "message": {"content": json.dumps({"thought": "auto", "column": column})}
    }
    return client


# ---------------------------------------------------------------------------
# Test 1: Happy-path Connect 4 via run_remote_seat
# ---------------------------------------------------------------------------


def test_remote_demo_happy_path_connect4(running_server: RunningServer) -> None:
    """run_remote_seat() drives a full Connect 4 match; both transcripts finish."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "a"}, {"label": "b"}],
        )

        # Seat 0 always plays column 0; seat 1 always plays column 1.
        # Seat 0 wins vertically after 7 turns (default 6x7 board).
        (result0, transcript0), (result1, transcript1) = await asyncio.gather(
            run_remote_seat(
                server_url=match["seat_0_url"],
                seat=0,
                game_id="connect4",
                model="stub",
                client=_stub_client_returning(0),
            ),
            run_remote_seat(
                server_url=match["seat_1_url"],
                seat=1,
                game_id="connect4",
                model="stub",
                client=_stub_client_returning(1),
            ),
        )

        assert transcript0.lifecycle == "finished"
        assert transcript1.lifecycle == "finished"

        # Validate transcript against the game definition.
        registry = build_default_registry()
        definition = registry.get("connect4")
        loaded = validate_runtime_transcript(definition, transcript0.model_dump(mode="json"))
        assert loaded is not None

        # Both seats should observe the same canonical game.
        assert transcript0.match_transcript == transcript1.match_transcript

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 2: Abort (peer_disconnected) when seat 1 drops connection
# ---------------------------------------------------------------------------


def test_remote_demo_abort_peer_disconnected(running_server: RunningServer) -> None:
    """Seat 1 closes its WS mid-match; seat 0 receives MatchAbortedError(peer_disconnected)."""

    async def run() -> None:
        # Use a short disconnect grace so the abort arrives quickly.
        match = _create_match(
            running_server.http_base_url,
            "connect4",
            players=[{"label": "a"}, {"label": "b"}],
            disconnect_grace_ms=300,
        )

        async def seat1_disconnect() -> None:
            """Connect seat 1, receive a couple of events, then close abruptly."""
            session = await Session.connect(match["seat_1_url"], 1)
            # Drain up to 3 events (match_state, maybe observation), then drop.
            for _ in range(3):
                try:
                    await asyncio.wait_for(session.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    break
            await session.close()

        # Seat 0 drives normally; seat 1 disconnects.
        aborted_error: MatchAbortedError | None = None

        async def seat0_task() -> None:
            nonlocal aborted_error
            try:
                await run_remote_seat(
                    server_url=match["seat_0_url"],
                    seat=0,
                    game_id="connect4",
                    model="stub",
                    client=_stub_client_returning(0),
                )
            except MatchAbortedError as exc:
                aborted_error = exc

        await asyncio.gather(seat0_task(), seat1_disconnect())

        assert aborted_error is not None, "Expected seat 0 to receive MatchAbortedError"
        transcript = aborted_error.transcript
        assert transcript.lifecycle == "aborted"
        assert transcript.abort is not None
        assert transcript.abort.reason == "peer_disconnected", (
            f"Expected peer_disconnected, got {transcript.abort.reason!r}"
        )

        # Validate the aborted transcript (match_transcript may be None).
        registry = build_default_registry()
        definition = registry.get("connect4")
        validate_runtime_transcript(definition, transcript.model_dump(mode="json"))

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Test 3: Nim smoke test via custom prompt_builder
# ---------------------------------------------------------------------------


class _FirstLegalNimPromptBuilder:
    """Stub prompt builder for Nim: always picks the first legal action."""

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        # Return a dummy message — the stub client will return the legal action JSON.
        legal = observation.legal_actions
        action = legal[0]
        payload = json.dumps(
            {"thought": "first-legal", "pile_index": action.pile_index, "count": action.count}
        )
        return [{"role": "user", "content": payload}]

    def parse_response(self, content: str, observation: Any) -> Any | None:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None
        pile_index = data.get("pile_index")
        count = data.get("count")
        if not isinstance(pile_index, int) or not isinstance(count, int):
            return None
        from arena.games.nim.actions import TakeObjects
        try:
            action = TakeObjects(pile_index=pile_index, count=count)
        except ValueError:
            return None
        if action not in observation.legal_actions:
            return None
        return action

    def format_spec(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "pile_index": {"type": "integer", "minimum": 0},
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["thought", "pile_index", "count"],
        }

    def describe_invalid(self, raw_content: str) -> str:
        return f"Invalid response: {raw_content[:200]}"


def _nim_stub_client(observation_supplier: list[Any]) -> Any:
    """MagicMock OllamaClient for Nim whose response echoes the last user message content.

    The _FirstLegalNimPromptBuilder encodes the chosen action JSON as the user message
    content, so echoing it back makes parse_response() succeed immediately.
    """

    def _chat(
        model: str,
        messages: list[dict[str, str]],
        format_spec: Any,
        seed: int,
        temperature: float,
    ) -> dict[str, Any]:
        # The last message content is the JSON action payload from _FirstLegalNimPromptBuilder.
        content = messages[-1]["content"] if messages else "{}"
        return {"message": {"content": content}}

    client = MagicMock(spec=OllamaClient)
    client.chat.side_effect = _chat
    return client


def test_remote_demo_nim_smoke(running_server: RunningServer) -> None:
    """run_remote_seat() drives a full Nim match using a first-legal stub prompt_builder."""

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            "nim",
            players=[{"label": "nim-0"}, {"label": "nim-1"}],
        )

        builder0 = _FirstLegalNimPromptBuilder()
        builder1 = _FirstLegalNimPromptBuilder()
        client0 = _nim_stub_client([])
        client1 = _nim_stub_client([])

        (result0, transcript0), (result1, transcript1) = await asyncio.gather(
            run_remote_seat(
                server_url=match["seat_0_url"],
                seat=0,
                game_id="nim",
                model="stub",
                client=client0,
                prompt_builder=builder0,
            ),
            run_remote_seat(
                server_url=match["seat_1_url"],
                seat=1,
                game_id="nim",
                model="stub",
                client=client1,
                prompt_builder=builder1,
            ),
        )

        assert transcript0.lifecycle == "finished"
        assert transcript1.lifecycle == "finished"

        registry = build_default_registry()
        definition = registry.get("nim")
        loaded = validate_runtime_transcript(definition, transcript0.model_dump(mode="json"))
        assert loaded is not None

    asyncio.run(run())
