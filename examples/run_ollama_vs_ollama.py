"""Run two Ollama-backed LLM agents against each other on a small Connect 4 board."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

MODEL_A = "llama3.2:latest"
MODEL_B = "qwen2.5:1.5b"


def run(
    out_dir: str | Path = "./out",
    *,
    host: str = "http://localhost:11434",
    max_retries: int = 3,
    client_factory: Any = None,
) -> int:
    """Run a Connect 4 match between two Ollama models.

    client_factory, when provided, is a callable(host) -> OllamaClient used
    for testing without a real daemon.

    Returns 0 on normal completion, 1 on abort.
    """
    from arena.adapters.in_process import TypedPayloadPolicyAdapter
    from arena.agents.ollama import OllamaAgent, OllamaClient
    from arena.agents.ollama.connect4 import Connect4PromptBuilder
    from arena.cli.play import play_match
    from arena.games.connect4 import Connect4Config, Connect4GameDefinition
    from arena.runtime import Arena, PlayerRecord

    definition = Connect4GameDefinition
    config = Connect4Config(rows=4, columns=4, connect_length=4)

    retry_sink: dict[int, list[tuple[int, str]]] = {}

    def _make_agent(model: str, seat: int) -> OllamaAgent:
        client = client_factory(host) if client_factory is not None else OllamaClient(host=host)
        seat_entries: list[tuple[int, str]] = []
        retry_sink[seat] = seat_entries

        def _cb(attempt: int, reason: str) -> None:
            seat_entries.append((attempt, reason))

        return OllamaAgent(
            client=client,
            model=model,
            prompt_builder=Connect4PromptBuilder(),
            max_retries=max_retries,
            seed=0,
            temperature=0.0,
            retry_callback=_cb,
        )

    agent_a = _make_agent(MODEL_A, 0)
    agent_b = _make_agent(MODEL_B, 1)

    players = (
        PlayerRecord(player_id="agent-a", seat=0, label=MODEL_A),
        PlayerRecord(player_id="agent-b", seat=1, label=MODEL_B),
    )
    policies = {
        0: TypedPayloadPolicyAdapter(definition, agent_a),
        1: TypedPayloadPolicyAdapter(definition, agent_b),
    }

    return play_match(
        definition,
        config,
        players,
        policies,
        out_dir=out_dir,
        arena=Arena(),
        retry_sink=retry_sink,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run two Ollama models against each other.")
    parser.add_argument("--out-dir", default="./out")
    parser.add_argument("--host", default="http://localhost:11434")
    parser.add_argument("--max-retries", type=int, default=3, dest="max_retries")
    args = parser.parse_args()
    sys.exit(run(args.out_dir, host=args.host, max_retries=args.max_retries))
