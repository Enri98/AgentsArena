"""Boundary serializers for Rock-Paper-Scissors config, actions, state, and observations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping
from arena.games.rps.actions import Throw
from arena.games.rps.config import (
    DEFAULT_MAX_ROUNDS,
    DEFAULT_TARGET_WINS,
    MAX_ROUNDS_CAP,
    MAX_TARGET_WINS,
    RpsConfig,
)
from arena.games.rps.observation import RpsObservation
from arena.games.rps.state import RoundResult, RpsState

_T = TypeVar("_T")
_STRICT = ConfigDict(extra="forbid", strict=True)

Shape = Literal["rock", "paper", "scissors"]


class RpsConfigPayload(BaseModel):
    model_config = _STRICT

    target_wins: int = Field(default=DEFAULT_TARGET_WINS, ge=1, le=MAX_TARGET_WINS)
    max_rounds: int = Field(default=DEFAULT_MAX_ROUNDS, ge=1, le=MAX_ROUNDS_CAP)


class ThrowPayload(BaseModel):
    model_config = _STRICT

    shape: Shape


class RoundResultPayload(BaseModel):
    model_config = _STRICT

    throws: list[Shape] = Field(min_length=2, max_length=2)
    winner: int | None = Field(ge=0, le=1)


class RpsStatePayload(BaseModel):
    model_config = _STRICT

    wins: list[int] = Field(min_length=2, max_length=2)
    rounds_played: int = Field(ge=0)
    target_wins: int = Field(ge=1, le=MAX_TARGET_WINS)
    max_rounds: int = Field(ge=1, le=MAX_ROUNDS_CAP)
    last_round: RoundResultPayload | None = None


class RpsObservationPayload(BaseModel):
    model_config = _STRICT

    seat: int = Field(ge=0, le=1)
    wins: list[int] = Field(min_length=2, max_length=2)
    rounds_played: int = Field(ge=0)
    target_wins: int = Field(ge=1, le=MAX_TARGET_WINS)
    max_rounds: int = Field(ge=1, le=MAX_ROUNDS_CAP)
    last_round: RoundResultPayload | None = None
    legal_actions: list[ThrowPayload]


def _expect(value: object, kind: type[_T]) -> _T:
    if not isinstance(value, kind):
        raise TypeError(f"expected {kind.__name__}, got {type(value).__name__}")
    return value


def _dump_round(result: RoundResult | None) -> RoundResultPayload | None:
    if result is None:
        return None
    return RoundResultPayload(throws=list(result.throws), winner=result.winner)


def _load_round(payload: RoundResultPayload | None) -> RoundResult | None:
    if payload is None:
        return None
    return RoundResult(throws=(payload.throws[0], payload.throws[1]), winner=payload.winner)


class RpsSerializer:
    """Boundary serializer for Rock-Paper-Scissors domain models."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        cfg = _expect(config, RpsConfig)
        return RpsConfigPayload.model_validate(cfg.model_dump()).model_dump(mode="json")

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return RpsConfig(**RpsConfigPayload.model_validate(payload).model_dump())

    def dump_state(self, state: object) -> JSONMapping:
        s = _expect(state, RpsState)
        return RpsStatePayload(
            wins=list(s.wins),
            rounds_played=s.rounds_played,
            target_wins=s.target_wins,
            max_rounds=s.max_rounds,
            last_round=_dump_round(s.last_round),
        ).model_dump(mode="json")

    def load_state(self, payload: JSONMapping) -> object:
        p = RpsStatePayload.model_validate(payload)
        return RpsState(
            wins=(p.wins[0], p.wins[1]),
            rounds_played=p.rounds_played,
            target_wins=p.target_wins,
            max_rounds=p.max_rounds,
            last_round=_load_round(p.last_round),
        )

    def dump_action(self, action: object) -> JSONMapping:
        a = _expect(action, Throw)
        return ThrowPayload(shape=a.shape).model_dump(mode="json")

    def load_action(self, payload: JSONMapping) -> object:
        return Throw(shape=ThrowPayload.model_validate(payload).shape)

    def dump_observation(self, observation: object) -> JSONMapping:
        o = _expect(observation, RpsObservation)
        return RpsObservationPayload(
            seat=o.seat,
            wins=list(o.wins),
            rounds_played=o.rounds_played,
            target_wins=o.target_wins,
            max_rounds=o.max_rounds,
            last_round=_dump_round(o.last_round),
            legal_actions=[ThrowPayload(shape=a.shape) for a in o.legal_actions],
        ).model_dump(mode="json")

    def load_observation(self, payload: JSONMapping) -> object:
        p = RpsObservationPayload.model_validate(payload)
        return RpsObservation(
            seat=p.seat,
            wins=(p.wins[0], p.wins[1]),
            rounds_played=p.rounds_played,
            target_wins=p.target_wins,
            max_rounds=p.max_rounds,
            last_round=_load_round(p.last_round),
            legal_actions=tuple(Throw(shape=a.shape) for a in p.legal_actions),
        )


__all__: Sequence[str] = [
    "RoundResultPayload",
    "RpsConfigPayload",
    "RpsObservationPayload",
    "RpsSerializer",
    "RpsStatePayload",
    "ThrowPayload",
]
