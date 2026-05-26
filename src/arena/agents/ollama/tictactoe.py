from __future__ import annotations

import json
from typing import Any

from arena.agents.ollama._adapters import OllamaGameAdapter, register_ollama_adapter
from arena.cli.games.tictactoe import numpad_action, render_board_plain
from arena.games.tictactoe.actions import PlaceMark
from arena.games.tictactoe.definition import TICTACTOE_GAME_ID

_SEAT_SYMBOLS = ("X", "O")


class TicTacToePromptBuilder:
    """Build Ollama chat messages and parse responses for Tic-Tac-Toe."""

    SYSTEM_PROMPT = (
        "You are an expert Tic-Tac-Toe player. "
        "The game is played on a 3x3 grid. "
        "The first player to make three in a row horizontally, vertically, or diagonally wins. "
        "With perfect play the game is a draw.\n\n"
        "Strategy:\n"
        "- The center cell (key 5) is strongest. Take it if available on the first move.\n"
        "- If you can make three in a row this turn, do it.\n"
        "- If your opponent has two in a row that can extend to three, you MUST block.\n"
        "- Create forks: positions where you have two open winning lines simultaneously.\n\n"
        "Positions are identified by numpad keys 1-9 "
        "(1=top-left, 2=top-center, 3=top-right, "
        "4=mid-left, 5=center, 6=mid-right, "
        "7=bottom-left, 8=bottom-center, 9=bottom-right).\n\n"
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
        legal_keys = _legal_keys(observation.legal_actions)
        symbol_grid = [
            [_cell_symbol(v, my_symbol, opp_symbol, seat) for v in row]
            for row in board_payload
        ]
        user_lines = [
            f"YOU ARE {my_symbol}. Your opponent is {opp_symbol}.",
            f"You play seat {seat}; opponent plays seat {opponent_seat}.",
            f"Board:\n{board_str}",
            f"Board as nested rows of symbols: {json.dumps(symbol_grid)}",
            f"Legal keys you may play: {legal_keys}",
            f"Reminder: your move places an {my_symbol} at the chosen key.",
            'Respond with a JSON object: {"thought": "<one short sentence about your '
            'move>", "key": <integer 1-9>}',
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
            "properties": {
                "thought": {"type": "string"},
                "key": {"type": "integer", "minimum": 1, "maximum": 9},
            },
            "required": ["thought", "key"],
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


def _cell_symbol(value: int, my_symbol: str, opp_symbol: str, seat: int) -> str:
    if value == 0:
        return "."
    if value == seat + 1:
        return my_symbol
    return opp_symbol


def _legal_keys(legal_actions: tuple[PlaceMark, ...]) -> list[int]:
    return sorted(
        _REVERSE_NUMPAD[(a.row, a.column)]
        for a in legal_actions
        if (a.row, a.column) in _REVERSE_NUMPAD
    )


register_ollama_adapter(
    OllamaGameAdapter(
        game_id=TICTACTOE_GAME_ID,
        prompt_builder_factory=TicTacToePromptBuilder,
    )
)


__all__: tuple[str, ...] = ("TicTacToePromptBuilder",)
