"""Connect 4 rules engine."""

from __future__ import annotations

from arena.core.actions import Action
from arena.core.events import DomainEvent
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Draw, RuleResult, Win
from arena.core.rules_engine import TransitionResult
from arena.core.types import Seat
from arena.games.connect4.actions import DropDisc
from arena.games.connect4.config import Connect4Config
from arena.games.connect4.events import DiscDropped, GameDrawn, WinnerDetected
from arena.games.connect4.observation import Connect4Observation
from arena.games.connect4.state import EMPTY_CELL, Connect4State, disc_for_seat


class Connect4RulesEngine:
    """Rules engine scaffold for Connect 4."""

    def __init__(self, config: Connect4Config | None = None) -> None:
        self._config = config or Connect4Config()

    def initial_state(self, config: Connect4Config) -> Connect4State:
        self._config = config
        board = tuple(
            tuple(EMPTY_CELL for _ in range(config.columns))
            for _ in range(config.rows)
        )
        return Connect4State(board=board, current_seat=0)

    def current_seat(self, state: Connect4State) -> Seat:
        return state.current_seat

    def legal_actions(self, state: Connect4State, seat: Seat) -> tuple[DropDisc, ...]:
        if self.is_terminal(state):
            return ()

        if seat != self.current_seat(state):
            return ()

        return tuple(
            DropDisc(column=column)
            for column in range(self._column_count(state))
            if state.board[0][column] == EMPTY_CELL
        )

    def validate_action(self, state: Connect4State, seat: Seat, action: Action) -> None:
        if self.is_terminal(state):
            raise GameFinished("Connect 4 is already finished.")

        if seat != self.current_seat(state):
            raise WrongPlayer(
                "The provided seat is not active.",
                details={"seat": seat, "current_seat": self.current_seat(state)},
            )

        if not isinstance(action, DropDisc):
            raise IllegalAction(
                "Connect 4 requires DropDisc actions.",
                details={"action_type": type(action).__name__},
            )

        if action.column >= self._column_count(state):
            raise IllegalAction(
                "The selected column is outside the board.",
                details={"column": action.column},
            )

        if state.board[0][action.column] != EMPTY_CELL:
            raise IllegalAction(
                "The selected column is full.",
                details={"column": action.column},
            )

    def apply_action(
        self,
        state: Connect4State,
        seat: Seat,
        action: DropDisc,
    ) -> TransitionResult[Connect4State, DomainEvent, RuleResult | None]:
        self.validate_action(state, seat, action)

        row = self._drop_row(state, action.column)
        assert row is not None  # validated columns are guaranteed to contain a landing row

        next_board = self._board_with_disc(state, row, action.column, disc_for_seat(seat))
        winning_seat = self._winner_from_last_move(next_board, row, action.column)

        events: list[DomainEvent] = [DiscDropped(seat=seat, column=action.column, row=row)]
        result: RuleResult | None = None

        if winning_seat is not None:
            events.append(WinnerDetected(winning_seat=winning_seat))
            result = Win(seat=winning_seat)
            next_seat = seat
        elif self._board_is_full_cells(next_board):
            events.append(GameDrawn())
            result = Draw()
            next_seat = seat
        else:
            next_seat = self._other_seat(seat)

        next_state = Connect4State(board=next_board, current_seat=next_seat)
        return TransitionResult(state=next_state, events=tuple(events), result=result)

    def is_terminal(self, state: Connect4State) -> bool:
        return self.result(state) is not None

    def result(self, state: Connect4State) -> RuleResult | None:
        winning_seat = self._winner_on_board(state.board)
        if winning_seat is not None:
            return Win(seat=winning_seat)

        if self._board_is_full(state):
            return Draw()
        return None

    def observation(self, state: Connect4State, seat: Seat) -> Connect4Observation:
        return Connect4Observation(
            seat=seat,
            board=state.board,
            current_seat=state.current_seat,
            legal_actions=self.legal_actions(state, seat),
        )

    def _board_is_full(self, state: Connect4State) -> bool:
        return self._board_is_full_cells(state.board)

    def _column_count(self, state: Connect4State) -> int:
        return len(state.board[0])

    def _row_count(self, state: Connect4State) -> int:
        return len(state.board)

    def _drop_row(self, state: Connect4State, column: int) -> int | None:
        for row in range(self._row_count(state) - 1, -1, -1):
            if state.board[row][column] == EMPTY_CELL:
                return row
        return None

    def _board_with_disc(
        self,
        state: Connect4State,
        row: int,
        column: int,
        disc_value: int,
    ) -> tuple[tuple[int, ...], ...]:
        return tuple(
            tuple(
                disc_value if row_index == row and column_index == column else cell
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
        disc_value = board[row][column]
        if disc_value == EMPTY_CELL:
            return None

        directions = ((1, 0), (0, 1), (1, 1), (1, -1))
        for row_step, column_step in directions:
            contiguous = 1
            contiguous += self._count_direction(
                board,
                row,
                column,
                row_step,
                column_step,
                disc_value,
            )
            contiguous += self._count_direction(
                board,
                row,
                column,
                -row_step,
                -column_step,
                disc_value,
            )
            if contiguous >= self._connect_length():
                return disc_value - 1
        return None

    def _count_direction(
        self,
        board: tuple[tuple[int, ...], ...],
        row: int,
        column: int,
        row_step: int,
        column_step: int,
        disc_value: int,
    ) -> int:
        count = 0
        row += row_step
        column += column_step

        while (
            0 <= row < len(board)
            and 0 <= column < len(board[0])
            and board[row][column] == disc_value
        ):
            count += 1
            row += row_step
            column += column_step

        return count

    def _board_is_full_cells(self, board: tuple[tuple[int, ...], ...]) -> bool:
        return all(cell != EMPTY_CELL for row in board for cell in row)

    def _connect_length(self) -> int:
        return self._config.connect_length

    def _other_seat(self, seat: Seat) -> Seat:
        return 1 if seat == 0 else 0


__all__ = ["Connect4RulesEngine"]
