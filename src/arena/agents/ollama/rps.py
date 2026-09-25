"""Ollama prompt builder and response parser for Rock-Paper-Scissors."""

from __future__ import annotations

import json
from typing import Any

from arena.agents.ollama._adapters import OllamaGameAdapter, register_ollama_adapter
from arena.games.rps.actions import SHAPES, Throw
from arena.games.rps.definition import RPS_GAME_ID


class RpsPromptBuilder:
    """Build Ollama chat messages and parse responses for Rock-Paper-Scissors."""

    SYSTEM_PROMPT = (
        "You are playing Rock-Paper-Scissors against another player.\n"
        "Each round you both throw at the same time, without seeing the other's throw:\n"
        "- rock beats scissors, scissors beats paper, paper beats rock;\n"
        "- the same throw is a tie and scores nobody.\n"
        "The first player to win the target number of rounds takes the match.\n\n"
        "Strategy: a predictable player loses. Look at the opponent's past throws for a "
        "pattern (repeating a throw, or switching to what would have beaten their last "
        "one) and counter it; with no pattern, vary your throws.\n\n"
        "Respond with a JSON object choosing rock, paper or scissors."
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        me = observation.seat
        opponent = 1 - me
        wins = observation.wins
        user_lines = [
            f"You are seat {me}. First to {observation.target_wins} round wins takes the "
            f"match (at most {observation.max_rounds} rounds).",
            f"Score: you {wins[me]}, opponent {wins[opponent]}. "
            f"Rounds played: {observation.rounds_played}.",
        ]
        last = observation.last_round
        if last is not None:
            outcome = (
                "a tie" if last.winner is None else ("you won it" if last.winner == me
                                                     else "the opponent won it")
            )
            user_lines.append(
                f"Last round: you threw {last.throws[me]}, the opponent threw "
                f"{last.throws[opponent]} ({outcome})."
            )
        user_lines += [
            f"Legal throws: {json.dumps([a.shape for a in observation.legal_actions])}",
            'Respond with JSON: {"thought": "<one sentence>", '
            '"shape": "rock" | "paper" | "scissors"}',
        ]
        if retry_feedback:
            feedback_items = "\n".join(f" - {f}" for f in retry_feedback)
            user_lines.append(f"Previous attempts were rejected:\n{feedback_items}")
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_lines)},
        ]

    def parse_response(self, content: str, observation: Any) -> Any | None:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        shape = data.get("shape")
        if not isinstance(shape, str):
            return None
        shape = shape.strip().lower()
        if shape not in SHAPES:
            return None
        action = Throw(shape=shape)
        return action if action in observation.legal_actions else None

    def format_spec(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "shape": {"type": "string", "enum": list(SHAPES)},
            },
            "required": ["thought", "shape"],
        }

    def describe_invalid(self, raw_content: str) -> str:
        return (
            "Response was not a throw: expected shape 'rock', 'paper' or 'scissors'. "
            f"Raw content: {raw_content[:200]}"
        )


register_ollama_adapter(
    OllamaGameAdapter(
        game_id=RPS_GAME_ID,
        prompt_builder_factory=RpsPromptBuilder,
    )
)


__all__: tuple[str, ...] = ("RpsPromptBuilder",)
