"""Ollama prompt builder and response parser for Nim."""

from __future__ import annotations

import json
from typing import Any

from arena.games.nim.actions import TakeObjects


class NimPromptBuilder:
    """Build Ollama chat messages and parse responses for Nim."""

    SYSTEM_PROMPT = (
        "You are an expert Nim player. "
        "Nim is played with several piles of objects. "
        "On each turn, a player must take at least one object from exactly one pile. "
        "The player who takes the LAST object WINS (normal play convention).\n\n"
        "Winning strategy (nim-sum):\n"
        "- Compute the nim-sum: XOR of all pile sizes.\n"
        "- If the nim-sum is non-zero, you are in a winning position. "
        "Find a pile to take from so the nim-sum becomes 0 after your move.\n"
        "- If the nim-sum is zero, any move you make gives the opponent a winning position. "
        "In that case, make a reasonable move (e.g. take 1 from the largest pile).\n\n"
        "Respond with a JSON object indicating which pile to take from and how many to take."
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        piles: list[int] = list(observation.piles)
        nim_sum = 0
        for p in piles:
            nim_sum ^= p
        pile_lines = "\n".join(f"  Pile {i}: {size} objects" for i, size in enumerate(piles))
        legal = [
            {"pile_index": a.pile_index, "count": a.count} for a in observation.legal_actions
        ]
        user_lines = [
            f"You are seat {observation.current_seat}.",
            f"Current piles:\n{pile_lines}",
            f"Nim-sum (XOR of all piles): {nim_sum}",
            f"Legal actions: {json.dumps(legal)}",
            'Respond with JSON: {"thought": "<one sentence>", "pile_index": <int>, "count": <int>}',
        ]
        if retry_feedback:
            feedback_items = "\n".join(f" - {f}" for f in retry_feedback)
            user_lines.append(f"Previous attempts were rejected:\n{feedback_items}")
        user_content = "\n".join(user_lines)
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def parse_response(self, content: str, observation: Any) -> Any | None:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return None
        pile_index = data.get("pile_index")
        count = data.get("count")
        if not isinstance(pile_index, int) or not isinstance(count, int):
            return None
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
        return f"Response was not a valid legal action. Raw content: {raw_content[:200]}"


__all__: tuple[str, ...] = ("NimPromptBuilder",)
