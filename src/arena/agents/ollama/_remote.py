"""Run an Ollama-backed seat against a remote arena.server over WebSocket.

This is a thin convenience helper that bundles the typical Phase 31 wiring
(picking the right prompt builder + GameDefinition by ``game_id``, building an
:class:`OllamaAgent`, and bridging it onto the SDK ``choose()`` callback) into a
single ``run_remote_seat()`` call.

Used by ``examples/run_remote_demo.py`` and the Phase 34 integration tests so
neither has to duplicate the boilerplate.
"""

from __future__ import annotations

from typing import Any

# Importing the per-game submodules directly ensures their top-level
# register_ollama_adapter() calls fire even when arena.agents.ollama._remote
# is imported without first importing arena.agents.ollama.
from arena.agents.ollama import connect4 as _connect4  # noqa: F401
from arena.agents.ollama import nim as _nim  # noqa: F401
from arena.agents.ollama import tictactoe as _tictactoe  # noqa: F401
from arena.agents.ollama._adapters import OLLAMA_GAME_ADAPTERS
from arena.agents.ollama.agent import OllamaAgent, PromptBuilder
from arena.agents.ollama.client import OllamaClient

# arena.agents is permitted to depend on arena.cli (see connect4.py / tictactoe.py
# already importing arena.cli.games for board rendering). The SDK is reached
# transitively through arena.cli.remote, satisfying the import-boundary tests.
from arena.cli.remote import make_typed_agent_choose, run_remote_seat_async
from arena.games import build_default_registry

_DEFINITION_REGISTRY = build_default_registry()


def _resolve_definition(game_id: str) -> Any:
    try:
        return _DEFINITION_REGISTRY.get(game_id)
    except Exception as exc:
        raise ValueError(
            f"Unsupported game_id {game_id!r}. "
            f"Supported games: {sorted(OLLAMA_GAME_ADAPTERS)}."
        ) from exc


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
    if prompt_builder is None:
        try:
            adapter = OLLAMA_GAME_ADAPTERS[game_id]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported game_id {game_id!r}. "
                f"Supported games: {sorted(OLLAMA_GAME_ADAPTERS)}."
            ) from exc
        builder = adapter.prompt_builder_factory()
    else:
        builder = prompt_builder
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
