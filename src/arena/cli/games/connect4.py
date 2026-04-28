"""Terminal board renderer and input parser for Connect 4."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.games.connect4.actions import DropDisc

RESET = "\x1b[0m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"

_EMPTY = 0
_SEAT0 = 1
_SEAT1 = 2

_DISC_SEAT0 = f"{RED}●{RESET}"
_DISC_SEAT1 = f"{YELLOW}●{RESET}"
_EMPTY_CELL = f"{DIM}.{RESET}"

_COLUMNS = 7


def render_board(state_payload: Mapping[str, Any]) -> str:
    board: list[list[int]] = state_payload["board"]
    col_count = len(board[0]) if board else _COLUMNS
    header = DIM + " ".join(str(c) for c in range(col_count)) + RESET
    rows = [header]
    for row in board:
        cells = [_cell(v) for v in row]
        rows.append(" ".join(cells))
    return "\n".join(rows)


def _cell(value: int) -> str:
    if value == _SEAT0:
        return _DISC_SEAT0
    if value == _SEAT1:
        return _DISC_SEAT1
    return _EMPTY_CELL


def parse_input(line: str, observation: Any) -> DropDisc | None:
    """Parse a column index from *line* and return a legal DropDisc or None."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        col = int(stripped)
    except ValueError:
        return None
    action = DropDisc(column=col) if col >= 0 else None
    if action is None:
        return None
    if action in observation.legal_actions:
        return action
    return None


__all__: tuple[str, ...] = ("parse_input", "render_board")
