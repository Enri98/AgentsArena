"""Tic-Tac-Toe rules engine."""

from __future__ import annotations

from arena.core.actions import Action
from arena.core.events import DomainEvent
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Draw, RuleResult, Win
from arena.core.rules_engine import TransitionResult
from arena.core.types import Seat
from arena.games.tictactoe.actions import PlaceMark
from arena.games.tictactoe.config import TicTacToeConfig
from arena.games.tictactoe.events import GameDrawn, MarkPlaced, WinnerDetected
from arena.games.tictactoe.observation import TicTacToeObservation
from arena.games.tictactoe.state import (
    BOARD_SIZE,
    EMPTY_CELL,
    TicTacToeState,
    mark_for_seat,
)


class TicTacToeRulesEngine:
    """Rules engine scaffold for standard Tic-Tac-Toe."""

    def __init__(self, config: TicTacToeConfig | None = None) -> None:
        self._config = config or TicTacToeConfig()

    def initial_state(self, config: TicTacToeConfig) -> TicTacToeState:
        self._config = config
        board = tuple(tuple(EMPTY_CELL for _ in range(config.columns)) for _ in range(config.rows))
        return TicTacToeState(board=board, current_seat=0)

    def current_seat(self, state: TicTacToeState) -> Seat:
        return state.current_seat

    def legal_actions(self, state: TicTacToeState, seat: Seat) -> tuple[PlaceMark, ...]:
        if self.is_terminal(state) or seat != self.current_seat(state):
            return ()

        return tuple(
            PlaceMark(row=row, column=column)
            for row in range(BOARD_SIZE)
            for column in range(BOARD_SIZE)
            if state.board[row][column] == EMPTY_CELL
        )

    def validate_action(self, state: TicTacToeState, seat: Seat, action: Action) -> None:
        if self.is_terminal(state):
            raise GameFinished("Tic-Tac-Toe is already finished.")

        if seat != self.current_seat(state):
            raise WrongPlayer(
                "The provided seat is not active.",
                details={"seat": seat, "current_seat": self.current_seat(state)},
            )

        if not isinstance(action, PlaceMark):
            raise IllegalAction(
                "Tic-Tac-Toe requires PlaceMark actions.",
                details={"action_type": type(action).__name__},
            )

        if action.row < 0 or action.column < 0:
            raise IllegalAction(
                "The selected cell is outside the board.",
                details={"row": action.row, "column": action.column},
            )

        if action.row >= BOARD_SIZE or action.column >= BOARD_SIZE:
            raise IllegalAction(
                "The selected cell is outside the board.",
                details={"row": action.row, "column": action.column},
            )

        if state.board[action.row][action.column] != EMPTY_CELL:
            raise IllegalAction(
                "The selected cell is already occupied.",
                details={"row": action.row, "column": action.column},
            )

    def apply_action(
        self,
        state: TicTacToeState,
        seat: Seat,
        action: PlaceMark,
    ) -> TransitionResult[TicTacToeState, DomainEvent, RuleResult | None]:
        self.validate_action(state, seat, action)

        next_board = self._board_with_mark(state, action.row, action.column, mark_for_seat(seat))
        winning_seat = self._winner_from_last_move(next_board, action.row, action.column)

        events: list[DomainEvent] = [MarkPlaced(seat=seat, row=action.row, column=action.column)]
        result: RuleResult | None = None

        if winning_seat is not None:
            events.append(WinnerDetected(winning_seat=winning_seat))
            result = Win(seat=winning_seat)
            next_seat = seat
        elif self._board_is_full(next_board):
            events.append(GameDrawn())
            result = Draw()
            next_seat = seat
        else:
            next_seat = self._other_seat(seat)

        next_state = TicTacToeState(board=next_board, current_seat=next_seat)
        return TransitionResult(state=next_state, events=tuple(events), result=result)

    def is_terminal(self, state: TicTacToeState) -> bool:
        return self.result(state) is not None

    def result(self, state: TicTacToeState) -> RuleResult | None:
        winning_seat = self._winner_on_board(state.board)
        if winning_seat is not None:
            return Win(seat=winning_seat)

        if self._board_is_full(state.board):
            return Draw()
        return None

    def observation(self, state: TicTacToeState, seat: Seat) -> TicTacToeObservation:
        return TicTacToeObservation(
            seat=seat,
            board=state.board,
            current_seat=state.current_seat,
            legal_actions=self.legal_actions(state, seat),
        )

    def _board_with_mark(
        self,
        state: TicTacToeState,
        row: int,
        column: int,
        mark_value: int,
    ) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(
                mark_value if row_index == row and column_index == column else cell
                for column_index, cell in enumerate(board_row)
            )
            for row_index, board_row in enumerate(state.board)
        )

    def _winner_on_board(self, board: tuple[tuple[int, ...], ...]) -> Seat | None:
        for row_index, row in enumerate(board):
            for column_index, cell in enumerate(row):
                if cell == EMPTY_CELL:
                    continue
                if self._winner_from_last_move(board, row_index, column_index) is not None:
                    return cell - 1
        return None

    def _winner_from_last_move(
        self,
        board: tuple[tuple[int, ...], ...],
        row: int,
        column: int,
    ) -> Seat | None:
        mark_value = board[row][column]
        if mark_value == EMPTY_CELL:
            return None

        for row_step, column_step in ((1, 0), (0, 1), (1, 1), (1, -1)):
            contiguous = 1
            contiguous += self._count_direction(
                board, row, column, row_step, column_step, mark_value
            )
            contiguous += self._count_direction(
                board,
                row,
                column,
                -row_step,
                -column_step,
                mark_value,
            )
            if contiguous >= self._connect_length():
                return mark_value - 1
        return None

    def _count_direction(
        self,
        board: tuple[tuple[int, ...], ...],
        row: int,
        column: int,
        row_step: int,
        column_step: int,
        mark_value: int,
    ) -> int:
        count = 0
        row += row_step
        column += column_step

        while (
            0 <= row < len(board)
            and 0 <= column < len(board[0])
            and board[row][column] == mark_value
        ):
            count += 1
            row += row_step
            column += column_step

        return count

    def _board_is_full(self, board: tuple[tuple[int, ...], ...]) -> bool:
        return all(cell != EMPTY_CELL for row in board for cell in row)

    def _connect_length(self) -> int:
        return self._config.connect_length

    def _other_seat(self, seat: Seat) -> Seat:
        return 1 if seat == 0 else 0


__all__ = ["TicTacToeRulesEngine"]
