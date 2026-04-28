"""Terminal board renderer for Tic-Tac-Toe."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

RESET = "\x1b[0m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
BLUE = "\x1b[34m"

# Board cell values as defined by arena.games.tictactoe.state.
_EMPTY = 0
_SEAT0 = 1
_SEAT1 = 2

_MARK_SEAT0 = f"{RED}X{RESET}"
_MARK_SEAT1 = f"{BLUE}O{RESET}"
_EMPTY_CELL = f"{DIM}.{RESET}"

_SEPARATOR = "---+---+---"


def render_board(state_payload: Mapping[str, Any]) -> str:
    board: list[list[int]] = state_payload["board"]
    rendered_rows = [_row(row) for row in board]
    return f"\n{_SEPARATOR}\n".join(rendered_rows)


def _row(row: list[int]) -> str:
    return " | ".join(_cell(v) for v in row)


def _cell(value: int) -> str:
    if value == _SEAT0:
        return _MARK_SEAT0
    if value == _SEAT1:
        return _MARK_SEAT1
    return _EMPTY_CELL


__all__: tuple[str, ...] = ("render_board",)
