"""Terminal board renderer and input parser for Connect 4."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.cli.games._registry import CliGameAdapter, register_cli_adapter
from arena.games.connect4.actions import DropDisc
from arena.games.connect4.config import Connect4Config
from arena.games.connect4.definition import CONNECT4_GAME_ID

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


def render_board_plain(state_payload: Mapping[str, Any]) -> str:
    board: list[list[int]] = state_payload["board"]
    col_count = len(board[0]) if board else _COLUMNS
    header = " ".join(str(c) for c in range(col_count))
    rows = [header]
    for row in board:
        cells = [_cell_plain(v) for v in row]
        rows.append(" ".join(cells))
    return "\n".join(rows)


def _cell_plain(value: int) -> str:
    if value == _SEAT0:
        return "X"
    if value == _SEAT1:
        return "O"
    return "."


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


def _parse_scripted(spec: str) -> list[DropDisc]:
    return [DropDisc(column=int(v.strip())) for v in spec.split(",") if v.strip()]


def _config_from_args(args: Any) -> Connect4Config:
    return Connect4Config(
        rows=args.rows,
        columns=args.cols,
        connect_length=args.connect_length,
    )


register_cli_adapter(
    CliGameAdapter(
        game_id=CONNECT4_GAME_ID,
        renderer=render_board,
        plain_renderer=render_board_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)


__all__: tuple[str, ...] = ("parse_input", "render_board", "render_board_plain")
