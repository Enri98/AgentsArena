"""Ollama prompt builder and response parser for Pig."""

from __future__ import annotations

import json
from typing import Any

from arena.agents.ollama._adapters import OllamaGameAdapter, register_ollama_adapter
from arena.games.pig.actions import PIG_CHOICES, PigMove
from arena.games.pig.definition import PIG_GAME_ID


class PigPromptBuilder:
    """Build Ollama chat messages and parse responses for Pig."""

    SYSTEM_PROMPT = (
        "You are an expert player of Pig, a two-player dice game.\n"
        "On your turn you roll a six-sided die as many times as you like:\n"
        "- A roll of 2-6 adds to your TURN TOTAL.\n"
        "- A roll of 1 wipes out your turn total and ends your turn.\n"
        "- 'hold' banks your turn total into your SCORE and ends your turn.\n"
        "Every turn starts with a roll. The first player whose banked score reaches the "
        "target wins.\n\n"
        "Strategy:\n"
        "- A good default is to keep rolling until your turn total is about 20, then hold.\n"
        "- If holding now would reach the target, hold: you win immediately.\n"
        "- If your opponent is close to the target and you are far behind, take more risk.\n\n"
        "Respond with a JSON object choosing 'roll' or 'hold'."
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        me = observation.seat
        opponent = 1 - me
        scores = observation.scores
        target = observation.target_score
        turn_total = observation.turn_total
        legal = [a.choice for a in observation.legal_actions]

        user_lines = [
            f"You are seat {me}. Target score: {target}.",
            f"Your banked score: {scores[me]} (need {max(target - scores[me], 0)} more).",
            f"Opponent banked score: {scores[opponent]} "
            f"(needs {max(target - scores[opponent], 0)} more).",
            f"Your turn total so far: {turn_total}.",
        ]
        if turn_total and scores[me] + turn_total >= target:
            user_lines.append("Holding now reaches the target and wins the game.")
        user_lines += [
            f"Legal actions: {json.dumps(legal)}",
            'Respond with JSON: {"thought": "<one sentence>", "choice": "roll" | "hold"}',
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
        choice = data.get("choice")
        if not isinstance(choice, str):
            return None
        choice = choice.strip().lower()
        if choice not in PIG_CHOICES:
            return None
        action = PigMove(choice=choice)
        return action if action in observation.legal_actions else None

    def format_spec(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "choice": {"type": "string", "enum": list(PIG_CHOICES)},
            },
            "required": ["thought", "choice"],
        }

    def describe_invalid(self, raw_content: str) -> str:
        return (
            "Response was not a legal choice ('roll', or 'hold' once your turn total is "
            f"above 0). Raw content: {raw_content[:200]}"
        )


register_ollama_adapter(
    OllamaGameAdapter(
        game_id=PIG_GAME_ID,
        prompt_builder_factory=PigPromptBuilder,
    )
)


__all__: tuple[str, ...] = ("PigPromptBuilder",)
