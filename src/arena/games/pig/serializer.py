"""Boundary serializers for Pig config, actions, state, observations, and rolls."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping
from arena.games.pig.actions import DIE_FACES, DieRoll, PigMove
from arena.games.pig.config import DEFAULT_TARGET_SCORE, PigConfig
from arena.games.pig.observation import PigObservation
from arena.games.pig.state import PigState

_T = TypeVar("_T")


class PigConfigPayload(BaseModel):
    """JSON-facing payload for Pig configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    target_score: int = Field(default=DEFAULT_TARGET_SCORE, ge=1, le=1000)


class PigMovePayload(BaseModel):
    """JSON-facing payload for Pig actions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    choice: Literal["roll", "hold"]


class DieRollPayload(BaseModel):
    """JSON-facing payload for a recorded die roll (a chance outcome)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    face: int = Field(ge=1, le=DIE_FACES)


class PigStatePayload(BaseModel):
    """JSON-facing payload for Pig state snapshots."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scores: list[int] = Field(min_length=2, max_length=2)
    current_seat: int = Field(ge=0, le=1)
    turn_total: int = Field(ge=0)
    roll_pending: bool
    target_score: int = Field(ge=1)


class PigObservationPayload(BaseModel):
    """JSON-facing payload for Pig observations."""

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int = Field(ge=0, le=1)
    scores: list[int] = Field(min_length=2, max_length=2)
    current_seat: int = Field(ge=0, le=1)
    turn_total: int = Field(ge=0)
    target_score: int = Field(ge=1)
    legal_actions: list[PigMovePayload]


class PigSerializer:
    """Concrete boundary serializer for Pig domain models."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        pig_config = _expect(config, PigConfig)
        return PigConfigPayload.model_validate(pig_config.model_dump()).model_dump(mode="json")

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return PigConfig(**PigConfigPayload.model_validate(payload).model_dump())

    def dump_state(self, state: object) -> JSONMapping:
        pig_state = _expect(state, PigState)
        return PigStatePayload(
            scores=list(pig_state.scores),
            current_seat=pig_state.current_seat,
            turn_total=pig_state.turn_total,
            roll_pending=pig_state.roll_pending,
            target_score=pig_state.target_score,
        ).model_dump(mode="json")

    def load_state(self, payload: JSONMapping) -> object:
        state_payload = PigStatePayload.model_validate(payload)
        return PigState(
            scores=(state_payload.scores[0], state_payload.scores[1]),
            current_seat=state_payload.current_seat,
            turn_total=state_payload.turn_total,
            roll_pending=state_payload.roll_pending,
            target_score=state_payload.target_score,
        )

    def dump_action(self, action: object) -> JSONMapping:
        move = _expect(action, PigMove)
        return PigMovePayload(choice=move.choice).model_dump(mode="json")

    def load_action(self, payload: JSONMapping) -> object:
        return PigMove(choice=PigMovePayload.model_validate(payload).choice)

    def dump_observation(self, observation: object) -> JSONMapping:
        obs = _expect(observation, PigObservation)
        return PigObservationPayload(
            seat=obs.seat,
            scores=list(obs.scores),
            current_seat=obs.current_seat,
            turn_total=obs.turn_total,
            target_score=obs.target_score,
            legal_actions=[PigMovePayload(choice=a.choice) for a in obs.legal_actions],
        ).model_dump(mode="json")

    def load_observation(self, payload: JSONMapping) -> object:
        obs_payload = PigObservationPayload.model_validate(payload)
        return PigObservation(
            seat=obs_payload.seat,
            scores=(obs_payload.scores[0], obs_payload.scores[1]),
            current_seat=obs_payload.current_seat,
            turn_total=obs_payload.turn_total,
            target_score=obs_payload.target_score,
            legal_actions=tuple(PigMove(choice=a.choice) for a in obs_payload.legal_actions),
        )

    # -- chance outcomes (arena.core.chance) ---------------------------------

    def dump_chance_outcome(self, outcome: object) -> JSONMapping:
        roll = _expect(outcome, DieRoll)
        return DieRollPayload(face=roll.face).model_dump(mode="json")

    def load_chance_outcome(self, payload: JSONMapping) -> object:
        return DieRoll(face=DieRollPayload.model_validate(payload).face)


def _expect(value: object, expected: type[_T]) -> _T:
    if not isinstance(value, expected):
        raise TypeError(f"Expected {expected.__name__}, got {type(value).__name__}.")
    return value


__all__: Sequence[str] = [
    "DieRollPayload",
    "PigConfigPayload",
    "PigMovePayload",
    "PigObservationPayload",
    "PigSerializer",
    "PigStatePayload",
]
