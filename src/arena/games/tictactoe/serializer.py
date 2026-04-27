"""Boundary serializers for Tic-Tac-Toe config, actions, state, and observations."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping
from arena.games.tictactoe.actions import PlaceMark
from arena.games.tictactoe.config import TicTacToeConfig
from arena.games.tictactoe.observation import TicTacToeObservation
from arena.games.tictactoe.state import (
    EMPTY_CELL,
    SEAT0_MARK,
    SEAT1_MARK,
    TicTacToeBoard,
    TicTacToeState,
)


class TicTacToeConfigPayload(BaseModel):
    """JSON-facing payload for the standard Tic-Tac-Toe configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    rows: int = Field(default=3, ge=3)
    columns: int = Field(default=3, ge=3)
    connect_length: int = Field(default=3, ge=3)

    @model_validator(mode="after")
    def validate_standard_board(self) -> "TicTacToeConfigPayload":
        if (self.rows, self.columns, self.connect_length) != (3, 3, 3):
            raise ValueError("Tic-Tac-Toe uses a fixed 3x3 board with connect_length 3")
        return self


class PlaceMarkPayload(BaseModel):
    """JSON-facing payload for Tic-Tac-Toe actions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    row: int = Field(ge=0)
    column: int = Field(ge=0)


class TicTacToeObservationPayload(BaseModel):
    """JSON-facing payload for Tic-Tac-Toe observations."""

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int = Field(ge=0, le=1)
    board: list[list[int]]
    current_seat: int = Field(ge=0, le=1)
    legal_actions: list[PlaceMarkPayload]

    @model_validator(mode="after")
    def validate_board_shape(self) -> "TicTacToeObservationPayload":
        _validate_board_payload(self.board)
        return self


class TicTacToeStatePayload(BaseModel):
    """JSON-facing payload for Tic-Tac-Toe state snapshots."""

    model_config = ConfigDict(extra="forbid", strict=True)

    board: list[list[int]]
    current_seat: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_board_shape(self) -> "TicTacToeStatePayload":
        _validate_board_payload(self.board)
        return self


class TicTacToeSerializer:
    """Concrete boundary serializer for Tic-Tac-Toe domain models."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        tictactoe_config = _expect_tictactoe_config(config)
        payload = TicTacToeConfigPayload.model_validate(tictactoe_config.model_dump())
        return payload.model_dump(mode="json")

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        config_payload = TicTacToeConfigPayload.model_validate(payload)
        return TicTacToeConfig(**config_payload.model_dump())

    def dump_state(self, state: object) -> JSONMapping:
        tictactoe_state = _expect_tictactoe_state(state)
        payload = TicTacToeStatePayload(
            board=_board_to_payload(tictactoe_state.board),
            current_seat=tictactoe_state.current_seat,
        )
        return payload.model_dump(mode="json")

    def load_state(self, payload: JSONMapping) -> object:
        state_payload = TicTacToeStatePayload.model_validate(payload)
        return TicTacToeState(
            board=_payload_to_board(state_payload.board),
            current_seat=state_payload.current_seat,
        )

    def dump_action(self, action: object) -> JSONMapping:
        place_mark = _expect_place_mark(action)
        payload = PlaceMarkPayload(row=place_mark.row, column=place_mark.column)
        return payload.model_dump(mode="json")

    def load_action(self, payload: JSONMapping) -> object:
        action_payload = PlaceMarkPayload.model_validate(payload)
        return PlaceMark(row=action_payload.row, column=action_payload.column)

    def dump_observation(self, observation: object) -> JSONMapping:
        tictactoe_observation = _expect_tictactoe_observation(observation)
        payload = TicTacToeObservationPayload(
            seat=tictactoe_observation.seat,
            board=_board_to_payload(tictactoe_observation.board),
            current_seat=tictactoe_observation.current_seat,
            legal_actions=[
                PlaceMarkPayload(row=action.row, column=action.column)
                for action in tictactoe_observation.legal_actions
            ],
        )
        return payload.model_dump(mode="json")

    def load_observation(self, payload: JSONMapping) -> object:
        observation_payload = TicTacToeObservationPayload.model_validate(payload)
        return TicTacToeObservation(
            seat=observation_payload.seat,
            board=_payload_to_board(observation_payload.board),
            current_seat=observation_payload.current_seat,
            legal_actions=tuple(
                PlaceMark(row=action_payload.row, column=action_payload.column)
                for action_payload in observation_payload.legal_actions
            ),
        )


def _board_to_payload(board: TicTacToeBoard) -> list[list[int]]:
    return [list(row) for row in board]


def _payload_to_board(board: list[list[int]]) -> TicTacToeBoard:
    return tuple(tuple(row) for row in board)


def _expect_tictactoe_config(config: BaseGameConfig) -> TicTacToeConfig:
    if not isinstance(config, TicTacToeConfig):
        raise TypeError(f"Expected TicTacToeConfig, got {type(config).__name__}.")
    return config


def _expect_place_mark(action: object) -> PlaceMark:
    if not isinstance(action, PlaceMark):
        raise TypeError(f"Expected PlaceMark, got {type(action).__name__}.")
    return action


def _expect_tictactoe_observation(observation: object) -> TicTacToeObservation:
    if not isinstance(observation, TicTacToeObservation):
        raise TypeError(f"Expected TicTacToeObservation, got {type(observation).__name__}.")
    return observation


def _expect_tictactoe_state(state: object) -> TicTacToeState:
    if not isinstance(state, TicTacToeState):
        raise TypeError(f"Expected TicTacToeState, got {type(state).__name__}.")
    return state


def _validate_board_payload(board: list[list[int]]) -> None:
    valid_mark_values = {EMPTY_CELL, SEAT0_MARK, SEAT1_MARK}

    if not board:
        raise ValueError("board must contain exactly 3 rows")

    if len(board) != 3:
        raise ValueError("board must contain exactly 3 rows")

    row_length = len(board[0])
    if row_length != 3:
        raise ValueError("board rows must contain exactly 3 columns")

    for row in board:
        if len(row) != row_length:
            raise ValueError("board must be rectangular")
        for cell in row:
            if type(cell) is not int or cell not in valid_mark_values:
                raise ValueError("board cells must be integer Tic-Tac-Toe mark values")


__all__: Sequence[str] = [
    "PlaceMarkPayload",
    "TicTacToeConfigPayload",
    "TicTacToeObservationPayload",
    "TicTacToeSerializer",
    "TicTacToeStatePayload",
]
