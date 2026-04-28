"""Golden-output tests for the Tic-Tac-Toe board renderer."""

from __future__ import annotations

from arena.cli.games.tictactoe import render_board
from arena.games.tictactoe import TicTacToeGameDefinition
from arena.games.tictactoe.state import EMPTY_CELL, SEAT0_MARK, SEAT1_MARK, TicTacToeState

RESET = "\x1b[0m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
BLUE = "\x1b[34m"

_E = f"{DIM}.{RESET}"
_X = f"{RED}X{RESET}"
_O = f"{BLUE}O{RESET}"
_SEP = "---+---+---"


def _dump(state: TicTacToeState) -> dict:
    return TicTacToeGameDefinition.serializer.dump_state(state)


_EMPTY_EXPECTED = (
    f"{_E} | {_E} | {_E}\n"
    f"{_SEP}\n"
    f"{_E} | {_E} | {_E}\n"
    f"{_SEP}\n"
    f"{_E} | {_E} | {_E}"
)

_MID_EXPECTED = (
    f"{_X} | {_E} | {_E}\n"
    f"{_SEP}\n"
    f"{_E} | {_O} | {_E}\n"
    f"{_SEP}\n"
    f"{_E} | {_E} | {_E}"
)

_WIN_EXPECTED = (
    f"{_X} | {_X} | {_X}\n"
    f"{_SEP}\n"
    f"{_O} | {_O} | {_E}\n"
    f"{_SEP}\n"
    f"{_E} | {_E} | {_E}"
)


def test_render_empty_board_golden() -> None:
    state = TicTacToeState(
        board=tuple(tuple(EMPTY_CELL for _ in range(3)) for _ in range(3)),
        current_seat=0,
    )
    result = render_board(_dump(state))
    assert result == _EMPTY_EXPECTED


def test_render_empty_board_is_deterministic() -> None:
    state = TicTacToeState(
        board=tuple(tuple(EMPTY_CELL for _ in range(3)) for _ in range(3)),
        current_seat=0,
    )
    sp = _dump(state)
    assert render_board(sp) == render_board(sp)


def test_render_mid_game_board_golden() -> None:
    mid_board = [
        [SEAT0_MARK, 0, 0],
        [0, SEAT1_MARK, 0],
        [0, 0, 0],
    ]
    state = TicTacToeState(
        board=tuple(tuple(r) for r in mid_board), current_seat=1
    )
    result = render_board(_dump(state))
    assert result == _MID_EXPECTED


def test_render_mid_game_board_is_deterministic() -> None:
    mid_board = [
        [SEAT0_MARK, 0, 0],
        [0, SEAT1_MARK, 0],
        [0, 0, 0],
    ]
    state = TicTacToeState(
        board=tuple(tuple(r) for r in mid_board), current_seat=1
    )
    sp = _dump(state)
    assert render_board(sp) == render_board(sp)


def test_render_terminal_board_golden() -> None:
    win_board = [
        [SEAT0_MARK, SEAT0_MARK, SEAT0_MARK],
        [SEAT1_MARK, SEAT1_MARK, 0],
        [0, 0, 0],
    ]
    state = TicTacToeState(
        board=tuple(tuple(r) for r in win_board), current_seat=1
    )
    result = render_board(_dump(state))
    assert result == _WIN_EXPECTED


def test_render_terminal_board_is_deterministic() -> None:
    win_board = [
        [SEAT0_MARK, SEAT0_MARK, SEAT0_MARK],
        [SEAT1_MARK, SEAT1_MARK, 0],
        [0, 0, 0],
    ]
    state = TicTacToeState(
        board=tuple(tuple(r) for r in win_board), current_seat=1
    )
    sp = _dump(state)
    assert render_board(sp) == render_board(sp)
