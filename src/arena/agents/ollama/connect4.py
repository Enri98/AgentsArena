"""Connect 4 prompt builder and response parser for OllamaAgent."""

from __future__ import annotations

import json
from typing import Any

from arena.cli.games.connect4 import render_board
from arena.games.connect4.actions import DropDisc


class Connect4PromptBuilder:
    """Build Ollama chat messages and parse responses for Connect 4."""

    SYSTEM_PROMPT = (
        "You are playing Connect 4. "
        "Players alternate dropping discs into columns. "
        "The first player to connect four discs in a row "
        "(horizontally, vertically, or diagonally) wins. "
        "You are given the board state and the list of legal column indices. "
        'Respond ONLY with a JSON object {"column": <integer>}.'
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        board_payload = [list(row) for row in observation.board]
        board_str = render_board({"board": board_payload})
        legal_columns = [a.column for a in observation.legal_actions]
        snapshot = {
            "current_seat": observation.current_seat,
            "board": board_payload,
            "legal_actions": [{"column": c} for c in legal_columns],
        }
        user_lines = [
            f"Current player: seat {observation.current_seat}",
            f"Board:\n{board_str}",
            f"Snapshot: {json.dumps(snapshot)}",
            f"Legal columns: {legal_columns}",
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
        column = data.get("column")
        if not isinstance(column, int):
            return None
        action = DropDisc(column=column)
        if action not in observation.legal_actions:
            return None
        return action

    def format_spec(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"column": {"type": "integer"}},
            "required": ["column"],
        }

    def describe_invalid(self, raw_content: str) -> str:
        return f"Response was not a valid legal action. Raw content: {raw_content[:200]}"


__all__: tuple[str, ...] = ("Connect4PromptBuilder",)
