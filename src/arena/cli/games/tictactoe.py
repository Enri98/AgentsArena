"""Terminal board renderer and input parser for Tic-Tac-Toe."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.cli.games._registry import CliGameAdapter, register_cli_adapter
from arena.games.tictactoe.actions import PlaceMark
from arena.games.tictactoe.config import TicTacToeConfig
from arena.games.tictactoe.definition import TICTACTOE_GAME_ID

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


_SEPARATOR_PLAIN = "---+---+---"


def render_board_plain(state_payload: Mapping[str, Any]) -> str:
    board: list[list[int]] = state_payload["board"]
    rendered_rows = [_row_plain(row) for row in board]
    return f"\n{_SEPARATOR_PLAIN}\n".join(rendered_rows)


def _row_plain(row: list[int]) -> str:
    return " | ".join(_cell_plain(v) for v in row)


def _cell_plain(value: int) -> str:
    if value == _SEAT0:
        return "X"
    if value == _SEAT1:
        return "O"
    return "."


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


def _parse_scripted(spec: str) -> list[PlaceMark]:
    actions: list[PlaceMark] = []
    for v in spec.split(","):
        v = v.strip()
        if not v:
            continue
        actions.append(numpad_action(int(v)))
    return actions


def _config_from_args(_args: Any) -> TicTacToeConfig:
    return TicTacToeConfig()


register_cli_adapter(
    CliGameAdapter(
        game_id=TICTACTOE_GAME_ID,
        renderer=render_board,
        plain_renderer=render_board_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)


__all__: tuple[str, ...] = ("numpad_action", "parse_input", "render_board", "render_board_plain")
