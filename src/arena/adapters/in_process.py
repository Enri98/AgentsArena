"""Serialized in-process policy boundary for local matches."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.exceptions import ArenaCoreError
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import RuleResult
from arena.core.serializer import JSONMapping
from arena.match.local_match import LocalMatch, apply_match_action

ConfigT = TypeVar("ConfigT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
ResultT = TypeVar("ResultT", bound=RuleResult)

ADAPTER_PAYLOAD_SCHEMA_VERSION = 1


class ObservationRequestPayload(BaseModel):
    """JSON-safe observation request for an adapter-facing policy."""

    model_config = ConfigDict(extra="forbid", strict=True)

    game_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    seat: int = Field(ge=0)
    observation: JSONMapping


class ActionResponsePayload(BaseModel):
    """JSON-safe action response returned by an adapter-facing policy."""

    model_config = ConfigDict(extra="forbid", strict=True)

    game_id: str = Field(min_length=1)
    schema_version: int = Field(ge=1)
    seat: int = Field(ge=0)
    action: JSONMapping


class DomainErrorPayload(BaseModel):
    """JSON-safe representation of a simulation-domain error."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: JSONMapping | None = None


class PayloadPolicy(Protocol):
    """Select a serialized action from a serialized observation request."""

    def select_action(self, request: ObservationRequestPayload) -> ActionResponsePayload:
        """Return an adapter-facing action response."""


def build_observation_request(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
) -> ObservationRequestPayload:
    """Serialize the active seat's observation for adapter-facing policy code."""

    seat = match.rules_engine.current_seat(match.state)
    observation = match.rules_engine.observation(match.state, seat)
    return ObservationRequestPayload(
        game_id=match.definition.game_id,
        schema_version=ADAPTER_PAYLOAD_SCHEMA_VERSION,
        seat=seat,
        observation=match.definition.serializer.dump_observation(observation),
    )


def load_action_response(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    response: ActionResponsePayload,
) -> ActionT:
    """Rehydrate a typed action from an adapter-facing action response."""

    _ensure_response_matches_definition(definition, response)
    return cast(ActionT, definition.serializer.load_action(response.action))


def apply_payload_policy_turn(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    policy: PayloadPolicy,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Ask an adapter-facing policy for one action and apply it to a local match."""

    request = build_observation_request(match)
    response = policy.select_action(request)
    action = load_action_response(match.definition, response)
    return apply_match_action(match, response.seat, action)


def dump_domain_error(error: ArenaCoreError) -> DomainErrorPayload:
    """Preserve domain exception metadata for adapter-boundary callers."""

    return DomainErrorPayload(
        code=error.code,
        message=error.message,
        details=error.details,
    )


def _ensure_response_matches_definition(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    response: ActionResponsePayload,
) -> None:
    if response.game_id != definition.game_id:
        raise ValueError(
            f"Action response game_id {response.game_id!r} does not match {definition.game_id!r}."
        )

    if response.schema_version != ADAPTER_PAYLOAD_SCHEMA_VERSION:
        raise ValueError(
            (
                "Action response schema_version "
                f"{response.schema_version!r} does not match "
                f"{ADAPTER_PAYLOAD_SCHEMA_VERSION!r}."
            )
        )


__all__: Sequence[str] = [
    "ADAPTER_PAYLOAD_SCHEMA_VERSION",
    "ActionResponsePayload",
    "DomainErrorPayload",
    "ObservationRequestPayload",
    "PayloadPolicy",
    "apply_payload_policy_turn",
    "build_observation_request",
    "dump_domain_error",
    "load_action_response",
]
