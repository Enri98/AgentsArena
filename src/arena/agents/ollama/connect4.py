from __future__ import annotations

import json
from typing import Any

from arena.cli.games.connect4 import render_board_plain
from arena.games.connect4.actions import DropDisc

_SEAT_SYMBOLS = ("X", "O")


class Connect4PromptBuilder:
    """Build Ollama chat messages and parse responses for Connect 4."""

    SYSTEM_PROMPT = (
        "You are an expert Connect 4 player. "
        "The game is played on a vertical board. "
        "Discs drop to the lowest empty cell of the chosen column. "
        "The first player to make four in a row horizontally, vertically, or diagonally wins.\n\n"
        "Strategy:\n"
        "- Prefer the center columns. They participate in the most winning lines.\n"
        "- If your opponent has three discs that can extend to four on their next move,"
        " you MUST block.\n"
        "- If you have three discs that can extend to four, take the win immediately.\n"
        "- Watch for double threats: a single move that creates two simultaneous"
        " winning threats is unstoppable.\n"
        "- Avoid moves that let your opponent stack a winning piece directly above your move.\n\n"
        "Before answering, briefly think about the board. Then return your move as JSON."
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        seat = observation.current_seat
        opponent_seat = 1 - seat
        my_symbol = _SEAT_SYMBOLS[seat]
        opp_symbol = _SEAT_SYMBOLS[opponent_seat]
        board_payload = [list(row) for row in observation.board]
        board_str = render_board_plain({"board": board_payload})
        legal_columns = [a.column for a in observation.legal_actions]
        symbol_grid = [
            [_cell_symbol(v, my_symbol, opp_symbol, seat) for v in row]
            for row in board_payload
        ]
        user_lines = [
            f"YOU ARE {my_symbol}. Your opponent is {opp_symbol}.",
            f"You play seat {seat}; opponent plays seat {opponent_seat}.",
            f"Board (top row is row 0, bottom row is the floor):\n{board_str}",
            f"Board as nested rows of symbols: {json.dumps(symbol_grid)}",
            f"Legal columns you may drop into: {legal_columns}",
            f"Reminder: your move places an {my_symbol} in the lowest empty cell "
            f"of the chosen column.",
            'Respond with a JSON object: {"thought": "<one short sentence about your '
            'move>", "column": <integer>}',
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
            "properties": {
                "thought": {"type": "string"},
                "column": {"type": "integer"},
            },
            "required": ["thought", "column"],
        }

    def describe_invalid(self, raw_content: str) -> str:
        return f"Response was not a valid legal action. Raw content: {raw_content[:200]}"


def _cell_symbol(value: int, my_symbol: str, opp_symbol: str, seat: int) -> str:
    if value == 0:
        return "."
    if value == seat + 1:
        return my_symbol
    return opp_symbol


__all__: tuple[str, ...] = ("Connect4PromptBuilder",)
