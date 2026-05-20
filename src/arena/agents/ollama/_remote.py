"""Run an Ollama-backed seat against a remote arena.server over WebSocket.

This is a thin convenience helper that bundles the typical Phase 31 wiring
(picking the right prompt builder + GameDefinition by ``game_id``, building an
:class:`OllamaAgent`, and bridging it onto the SDK ``choose()`` callback) into a
single ``run_remote_seat()`` call.

Used by ``examples/run_remote_demo.py`` and the Phase 34 integration tests so
neither has to duplicate the boilerplate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arena.agents.ollama.agent import OllamaAgent, PromptBuilder
from arena.agents.ollama.client import OllamaClient
from arena.agents.ollama.connect4 import Connect4PromptBuilder
from arena.agents.ollama.nim import NimPromptBuilder
from arena.agents.ollama.tictactoe import TicTacToePromptBuilder

# arena.agents is permitted to depend on arena.cli (see connect4.py / tictactoe.py
# already importing arena.cli.games for board rendering). The SDK is reached
# transitively through arena.cli.remote, satisfying the import-boundary tests.
from arena.cli.remote import make_typed_agent_choose, run_remote_seat_async

_PROMPT_BUILDERS: dict[str, Callable[[], PromptBuilder]] = {
    "connect4": Connect4PromptBuilder,
    "tictactoe": TicTacToePromptBuilder,
    "nim": NimPromptBuilder,
}


def _resolve_definition(game_id: str) -> Any:
    if game_id == "connect4":
        from arena.games.connect4 import Connect4GameDefinition

        return Connect4GameDefinition
    if game_id == "tictactoe":
        from arena.games.tictactoe import TicTacToeGameDefinition

        return TicTacToeGameDefinition
    if game_id == "nim":
        from arena.games.nim import NimGameDefinition

        return NimGameDefinition
    raise ValueError(
        f"Unsupported game_id {game_id!r}. "
        f"Supported games: {sorted(_PROMPT_BUILDERS)}."
    )


async def run_remote_seat(
    *,
    server_url: str,
    seat: int,
    game_id: str,
    model: str,
    ollama_host: str = "http://127.0.0.1:11434",
    temperature: float = 0.0,
    seed: int = 0,
    max_retries: int = 3,
    use_format_spec: bool = True,
    timeout: float = 300.0,
    retry_sink: list[tuple[int, str]] | None = None,
    decision_sink: list[tuple[int, str]] | None = None,
    resume_token: str | None = None,
    client: OllamaClient | None = None,
    prompt_builder: PromptBuilder | None = None,
) -> tuple[dict[str, Any], Any]:
    """Drive a single Ollama-backed seat to completion against a remote server.

    Parameters
    ----------
    server_url:
        Pre-built WebSocket URL for this seat
        (e.g. ``ws://host/matches/{id}/play?seat=0``).
    seat:
        Integer seat id matching the URL's ``?seat=`` query.
    game_id:
        One of ``"connect4"``, ``"tictactoe"``, or ``"nim"``. Selects the
        :class:`PromptBuilder` and :class:`GameDefinition`.
    model:
        Ollama model name (e.g. ``"llama3.2"``).
    ollama_host:
        Base URL for the local Ollama HTTP API.
    retry_sink, decision_sink:
        Optional lists that receive ``(attempt, message)`` tuples from the
        agent's retry loop and emitted thoughts respectively. Mirrors the local
        CLI's per-seat sinks.
    client, prompt_builder:
        Test seams: override the default :class:`OllamaClient` /
        :class:`PromptBuilder` (e.g. to inject a stub HTTP client in unit
        tests).

    Returns
    -------
    ``(result_dict, transcript)`` from :func:`arena.sdk.connect`.

    Raises
    ------
    MatchAbortedError: if the server aborts the match before a result.
    ValueError: if ``game_id`` is not supported.
    """
    definition = _resolve_definition(game_id)
    builder = prompt_builder or _PROMPT_BUILDERS[game_id]()
    http_client = client or OllamaClient(host=ollama_host, timeout=timeout)

    retry_callback = None
    if retry_sink is not None:
        def retry_callback(attempt: int, reason: str) -> None:  # noqa: E306
            retry_sink.append((attempt, reason))

    decision_callback = None
    if decision_sink is not None:
        def decision_callback(attempt: int, thought: str) -> None:  # noqa: E306
            decision_sink.append((attempt, thought))

    agent = OllamaAgent(
        client=http_client,
        model=model,
        prompt_builder=builder,
        max_retries=max_retries,
        seed=seed,
        temperature=temperature,
        retry_callback=retry_callback,
        decision_callback=decision_callback,
        use_format_spec=use_format_spec,
    )

    choose = make_typed_agent_choose(agent, definition)

    return await run_remote_seat_async(
        server_url, seat, choose, resume_token=resume_token
    )


__all__: tuple[str, ...] = ("run_remote_seat",)
