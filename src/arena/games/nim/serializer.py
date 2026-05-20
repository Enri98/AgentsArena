"""Boundary serializers for Nim config, actions, state, and observations."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping
from arena.games.nim.actions import TakeObjects
from arena.games.nim.config import NimConfig
from arena.games.nim.observation import NimObservation
from arena.games.nim.state import NimState


class NimConfigPayload(BaseModel):
    """JSON-facing payload for Nim configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    num_piles: int = Field(default=3, ge=1)
    max_pile_size: int = Field(default=7, ge=1)


class TakeObjectsPayload(BaseModel):
    """JSON-facing payload for Nim actions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    pile_index: int = Field(ge=0)
    count: int = Field(ge=1)


class NimStatePayload(BaseModel):
    """JSON-facing payload for Nim state snapshots."""

    model_config = ConfigDict(extra="forbid", strict=True)

    piles: list[int]
    current_seat: int = Field(ge=0, le=1)


class NimObservationPayload(BaseModel):
    """JSON-facing payload for Nim observations."""

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int = Field(ge=0, le=1)
    piles: list[int]
    current_seat: int = Field(ge=0, le=1)
    legal_actions: list[TakeObjectsPayload]


class NimSerializer:
    """Concrete boundary serializer for Nim domain models."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        nim_config = _expect_nim_config(config)
        payload = NimConfigPayload.model_validate(nim_config.model_dump())
        return payload.model_dump(mode="json")

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        config_payload = NimConfigPayload.model_validate(payload)
        return NimConfig(**config_payload.model_dump())

    def dump_state(self, state: object) -> JSONMapping:
        nim_state = _expect_nim_state(state)
        payload = NimStatePayload(
            piles=list(nim_state.piles),
            current_seat=nim_state.current_seat,
        )
        return payload.model_dump(mode="json")

    def load_state(self, payload: JSONMapping) -> object:
        state_payload = NimStatePayload.model_validate(payload)
        return NimState(
            piles=tuple(state_payload.piles),
            current_seat=state_payload.current_seat,
        )

    def dump_action(self, action: object) -> JSONMapping:
        take = _expect_take_objects(action)
        payload = TakeObjectsPayload(pile_index=take.pile_index, count=take.count)
        return payload.model_dump(mode="json")

    def load_action(self, payload: JSONMapping) -> object:
        action_payload = TakeObjectsPayload.model_validate(payload)
        return TakeObjects(pile_index=action_payload.pile_index, count=action_payload.count)

    def dump_observation(self, observation: object) -> JSONMapping:
        nim_obs = _expect_nim_observation(observation)
        payload = NimObservationPayload(
            seat=nim_obs.seat,
            piles=list(nim_obs.piles),
            current_seat=nim_obs.current_seat,
            legal_actions=[
                TakeObjectsPayload(pile_index=a.pile_index, count=a.count)
                for a in nim_obs.legal_actions
            ],
        )
        return payload.model_dump(mode="json")

    def load_observation(self, payload: JSONMapping) -> object:
        obs_payload = NimObservationPayload.model_validate(payload)
        return NimObservation(
            seat=obs_payload.seat,
            piles=tuple(obs_payload.piles),
            current_seat=obs_payload.current_seat,
            legal_actions=tuple(
                TakeObjects(pile_index=a.pile_index, count=a.count)
                for a in obs_payload.legal_actions
            ),
        )


def _expect_nim_config(config: BaseGameConfig) -> NimConfig:
    if not isinstance(config, NimConfig):
        raise TypeError(f"Expected NimConfig, got {type(config).__name__}.")
    return config


def _expect_nim_state(state: object) -> NimState:
    if not isinstance(state, NimState):
        raise TypeError(f"Expected NimState, got {type(state).__name__}.")
    return state


def _expect_take_objects(action: object) -> TakeObjects:
    if not isinstance(action, TakeObjects):
        raise TypeError(f"Expected TakeObjects, got {type(action).__name__}.")
    return action


def _expect_nim_observation(observation: object) -> NimObservation:
    if not isinstance(observation, NimObservation):
        raise TypeError(f"Expected NimObservation, got {type(observation).__name__}.")
    return observation


__all__: Sequence[str] = [
    "NimConfigPayload",
    "NimObservationPayload",
    "NimSerializer",
    "NimStatePayload",
    "TakeObjectsPayload",
]
