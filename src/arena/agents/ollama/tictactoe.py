"""Tic-Tac-Toe prompt builder and response parser for OllamaAgent."""

from __future__ import annotations

import json
from typing import Any

from arena.cli.games.tictactoe import numpad_action, render_board
from arena.games.tictactoe.actions import PlaceMark


class TicTacToePromptBuilder:
    """Build Ollama chat messages and parse responses for Tic-Tac-Toe."""

    SYSTEM_PROMPT = (
        "You are playing Tic-Tac-Toe on a 3x3 board. "
        "Players alternate placing marks. "
        "The first player to place three marks in a row "
        "(horizontally, vertically, or diagonally) wins. "
        "Positions are identified by numpad keys 1-9 "
        "(1=top-left, 2=top-center, 3=top-right, "
        "4=mid-left, 5=center, 6=mid-right, "
        "7=bottom-left, 8=bottom-center, 9=bottom-right). "
        'Respond ONLY with a JSON object {"key": <integer>} '
        "where key is in range 1-9."
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        board_payload = [list(row) for row in observation.board]
        board_str = render_board({"board": board_payload})
        legal_keys = _legal_keys(observation.legal_actions)
        snapshot = {
            "current_seat": observation.current_seat,
            "board": board_payload,
            "legal_actions": [
                {"row": a.row, "column": a.column} for a in observation.legal_actions
            ],
        }
        user_lines = [
            f"Current player: seat {observation.current_seat}",
            f"Board:\n{board_str}",
            f"Snapshot: {json.dumps(snapshot)}",
            f"Legal keys: {legal_keys}",
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
        key = data.get("key")
        if not isinstance(key, int):
            return None
        try:
            action = numpad_action(key)
        except ValueError:
            return None
        if action not in observation.legal_actions:
            return None
        return action

    def format_spec(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"key": {"type": "integer", "minimum": 1, "maximum": 9}},
            "required": ["key"],
        }

    def describe_invalid(self, raw_content: str) -> str:
        return f"Response was not a valid legal action. Raw content: {raw_content[:200]}"


_REVERSE_NUMPAD: dict[tuple[int, int], int] = {
    (0, 0): 1,
    (0, 1): 2,
    (0, 2): 3,
    (1, 0): 4,
    (1, 1): 5,
    (1, 2): 6,
    (2, 0): 7,
    (2, 1): 8,
    (2, 2): 9,
}


def _legal_keys(legal_actions: tuple[PlaceMark, ...]) -> list[int]:
    return sorted(
        _REVERSE_NUMPAD[(a.row, a.column)]
        for a in legal_actions
        if (a.row, a.column) in _REVERSE_NUMPAD
    )


__all__: tuple[str, ...] = ("TicTacToePromptBuilder",)
