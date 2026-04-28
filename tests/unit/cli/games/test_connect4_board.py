"""Golden-output tests for the Connect 4 board renderer."""

from __future__ import annotations

from arena.cli.games.connect4 import render_board
from arena.games.connect4 import Connect4GameDefinition
from arena.games.connect4.state import EMPTY_CELL, SEAT0_DISC, SEAT1_DISC, Connect4State

RESET = "\x1b[0m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"

_E = f"{DIM}.{RESET}"
_S0 = f"{RED}●{RESET}"
_S1 = f"{YELLOW}●{RESET}"


def _dump(state: Connect4State) -> dict:
    return Connect4GameDefinition.serializer.dump_state(state)


def _empty_board(rows: int = 6, cols: int = 7) -> Connect4State:
    return Connect4State(
        board=tuple(tuple(EMPTY_CELL for _ in range(cols)) for _ in range(rows)),
        current_seat=0,
    )


_EMPTY_6x7_EXPECTED = (
    f"{DIM}0 1 2 3 4 5 6{RESET}\n"
    + "\n".join(
        " ".join(_E for _ in range(7))
        for _ in range(6)
    )
)

_MID_EXPECTED = (
    f"{DIM}0 1 2 3 4 5 6{RESET}\n"
    + "\n".join(" ".join(_E for _ in range(7)) for _ in range(5))
    + f"\n{_S0} {_S1} {_E} {_E} {_E} {_E} {_E}"
)

_WIN_4x4_EXPECTED = (
    f"{DIM}0 1 2 3{RESET}\n"
    f"{_S0} {_E} {_E} {_E}\n"
    f"{_S0} {_S1} {_E} {_E}\n"
    f"{_S0} {_S1} {_E} {_E}\n"
    f"{_S0} {_S1} {_E} {_E}"
)


def test_render_empty_board_golden() -> None:
    state = _empty_board()
    result = render_board(_dump(state))
    assert result == _EMPTY_6x7_EXPECTED


def test_render_empty_board_is_deterministic() -> None:
    state = _empty_board()
    sp = _dump(state)
    assert render_board(sp) == render_board(sp)


def test_render_mid_game_board_golden() -> None:
    mid_board = [
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0, 0, 0, 0],
    ]
    state = Connect4State(
        board=tuple(tuple(r) for r in mid_board), current_seat=0
    )
    result = render_board(_dump(state))
    assert result == _MID_EXPECTED


def test_render_mid_game_board_is_deterministic() -> None:
    mid_board = [
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0, 0, 0, 0],
    ]
    state = Connect4State(
        board=tuple(tuple(r) for r in mid_board), current_seat=0
    )
    sp = _dump(state)
    assert render_board(sp) == render_board(sp)


def test_render_terminal_board_golden() -> None:
    win_board = [
        [SEAT0_DISC, 0, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0],
    ]
    state = Connect4State(
        board=tuple(tuple(r) for r in win_board), current_seat=1
    )
    result = render_board(_dump(state))
    assert result == _WIN_4x4_EXPECTED


def test_render_terminal_board_is_deterministic() -> None:
    win_board = [
        [SEAT0_DISC, 0, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0],
        [SEAT0_DISC, SEAT1_DISC, 0, 0],
    ]
    state = Connect4State(
        board=tuple(tuple(r) for r in win_board), current_seat=1
    )
    sp = _dump(state)
    assert render_board(sp) == render_board(sp)
