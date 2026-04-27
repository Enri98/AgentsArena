"""Boundary serializers for Connect 4 config, actions, and observations."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping
from arena.games.connect4.actions import DropDisc
from arena.games.connect4.config import Connect4Config
from arena.games.connect4.observation import Connect4Observation
from arena.games.connect4.state import (
    EMPTY_CELL,
    SEAT0_DISC,
    SEAT1_DISC,
    Connect4Board,
    Connect4State,
)


class Connect4ConfigPayload(BaseModel):
    """JSON-facing payload for Connect 4 configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    rows: int = Field(ge=4)
    columns: int = Field(ge=4)
    connect_length: int = Field(ge=2)


class DropDiscPayload(BaseModel):
    """JSON-facing payload for Connect 4 actions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    column: int = Field(ge=0)


class Connect4ObservationPayload(BaseModel):
    """JSON-facing payload for Connect 4 observations."""

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int = Field(ge=0, le=1)
    board: list[list[int]]
    current_seat: int = Field(ge=0, le=1)
    legal_actions: list[DropDiscPayload]

    @model_validator(mode="after")
    def validate_board_shape(self) -> "Connect4ObservationPayload":
        _validate_board_payload(self.board)
        return self


class Connect4StatePayload(BaseModel):
    """JSON-facing payload for Connect 4 state snapshots."""

    model_config = ConfigDict(extra="forbid", strict=True)

    board: list[list[int]]
    current_seat: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_board_shape(self) -> "Connect4StatePayload":
        _validate_board_payload(self.board)
        return self


class Connect4Serializer:
    """Concrete boundary serializer for Connect 4 domain models."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        connect4_config = _expect_connect4_config(config)
        payload = Connect4ConfigPayload.model_validate(connect4_config.model_dump())
        return payload.model_dump(mode="json")

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        config_payload = Connect4ConfigPayload.model_validate(payload)
        return Connect4Config(**config_payload.model_dump())

    def dump_state(self, state: object) -> JSONMapping:
        connect4_state = _expect_connect4_state(state)
        payload = Connect4StatePayload(
            board=_board_to_payload(connect4_state.board),
            current_seat=connect4_state.current_seat,
        )
        return payload.model_dump(mode="json")

    def load_state(self, payload: JSONMapping) -> object:
        state_payload = Connect4StatePayload.model_validate(payload)
        return Connect4State(
            board=_payload_to_board(state_payload.board),
            current_seat=state_payload.current_seat,
        )

    def dump_action(self, action: object) -> JSONMapping:
        drop_disc = _expect_drop_disc(action)
        payload = DropDiscPayload(column=drop_disc.column)
        return payload.model_dump(mode="json")

    def load_action(self, payload: JSONMapping) -> object:
        action_payload = DropDiscPayload.model_validate(payload)
        return DropDisc(column=action_payload.column)

    def dump_observation(self, observation: object) -> JSONMapping:
        connect4_observation = _expect_connect4_observation(observation)
        payload = Connect4ObservationPayload(
            seat=connect4_observation.seat,
            board=_board_to_payload(connect4_observation.board),
            current_seat=connect4_observation.current_seat,
            legal_actions=[
                DropDiscPayload(column=action.column)
                for action in connect4_observation.legal_actions
            ],
        )
        return payload.model_dump(mode="json")

    def load_observation(self, payload: JSONMapping) -> object:
        observation_payload = Connect4ObservationPayload.model_validate(payload)
        return Connect4Observation(
            seat=observation_payload.seat,
            board=_payload_to_board(observation_payload.board),
            current_seat=observation_payload.current_seat,
            legal_actions=tuple(
                DropDisc(column=action_payload.column)
                for action_payload in observation_payload.legal_actions
            ),
        )


def _board_to_payload(board: Connect4Board) -> list[list[int]]:
    return [list(row) for row in board]


def _payload_to_board(board: list[list[int]]) -> Connect4Board:
    return tuple(tuple(row) for row in board)


def _expect_connect4_config(config: BaseGameConfig) -> Connect4Config:
    if not isinstance(config, Connect4Config):
        raise TypeError(f"Expected Connect4Config, got {type(config).__name__}.")
    return config


def _expect_drop_disc(action: object) -> DropDisc:
    if not isinstance(action, DropDisc):
        raise TypeError(f"Expected DropDisc, got {type(action).__name__}.")
    return action


def _expect_connect4_observation(observation: object) -> Connect4Observation:
    if not isinstance(observation, Connect4Observation):
        raise TypeError(f"Expected Connect4Observation, got {type(observation).__name__}.")
    return observation


def _expect_connect4_state(state: object) -> Connect4State:
    if not isinstance(state, Connect4State):
        raise TypeError(f"Expected Connect4State, got {type(state).__name__}.")
    return state


def _validate_board_payload(board: list[list[int]]) -> None:
    valid_disc_values = {EMPTY_CELL, SEAT0_DISC, SEAT1_DISC}

    if not board:
        raise ValueError("board must contain at least one row")

    row_length = len(board[0])
    if row_length == 0:
        raise ValueError("board rows must contain at least one column")

    for row in board:
        if len(row) != row_length:
            raise ValueError("board must be rectangular")
        for cell in row:
            if type(cell) is not int or cell not in valid_disc_values:
                raise ValueError("board cells must be integer Connect 4 disc values")


__all__: Sequence[str] = [
    "Connect4ConfigPayload",
    "Connect4ObservationPayload",
    "Connect4Serializer",
    "Connect4StatePayload",
    "DropDiscPayload",
]
