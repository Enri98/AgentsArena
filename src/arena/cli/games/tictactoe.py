"""Terminal board renderer and input parser for Tic-Tac-Toe."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.games.tictactoe.actions import PlaceMark

RESET = "\x1b[0m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
BLUE = "\x1b[34m"

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


_NUMPAD_MAP: dict[int, tuple[int, int]] = {
    1: (0, 0),
    2: (0, 1),
    3: (0, 2),
    4: (1, 0),
    5: (1, 1),
    6: (1, 2),
    7: (2, 0),
    8: (2, 1),
    9: (2, 2),
}


def numpad_action(key: int) -> PlaceMark:
    """Return the PlaceMark for numpad key 1-9.

    Raises ValueError for out-of-range keys.
    """
    coords = _NUMPAD_MAP.get(key)
    if coords is None:
        raise ValueError(f"Numpad key {key!r} is not in range 1-9.")
    return PlaceMark(row=coords[0], column=coords[1])


def parse_input(line: str, observation: Any) -> PlaceMark | None:
    """Parse a numpad key 1-9 from *line* and return a legal PlaceMark or None."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        key = int(stripped)
    except ValueError:
        return None
    try:
        action = numpad_action(key)
    except ValueError:
        return None
    if action in observation.legal_actions:
        return action
    return None


__all__: tuple[str, ...] = ("numpad_action", "parse_input", "render_board")
