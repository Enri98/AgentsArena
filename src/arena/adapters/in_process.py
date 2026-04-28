"""Serialized in-process policy boundary for local matches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

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


class InProcessAgent(Protocol[ObservationT, ActionT]):
    """Select a typed action from a typed observation."""

    def select_action(self, observation: ObservationT) -> ActionT:
        """Return the next typed action for the supplied observation."""


@dataclass(frozen=True)
class TypedPayloadPolicyAdapter(Generic[ConfigT, StateT, ActionT, ObservationT, ResultT]):
    """Adapt a typed in-process agent to the serialized payload policy contract."""

    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT]
    agent: InProcessAgent[ObservationT, ActionT]

    def select_action(self, request: ObservationRequestPayload) -> ActionResponsePayload:
        """Load the request observation, ask the typed agent, and dump its action."""

        _ensure_request_matches_definition(self.definition, request)
        observation = cast(
            ObservationT,
            self.definition.serializer.load_observation(request.observation),
        )
        action = self.agent.select_action(observation)
        return ActionResponsePayload(
            game_id=request.game_id,
            schema_version=request.schema_version,
            seat=request.seat,
            action=self.definition.serializer.dump_action(action),
        )


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
    _ensure_game_id_matches_definition(definition.game_id, response.game_id, "Action response")

    if response.schema_version != ADAPTER_PAYLOAD_SCHEMA_VERSION:
        raise ValueError(
            (
                "Action response schema_version "
                f"{response.schema_version!r} does not match "
                f"{ADAPTER_PAYLOAD_SCHEMA_VERSION!r}."
            )
        )


def _ensure_request_matches_definition(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    request: ObservationRequestPayload,
) -> None:
    _ensure_game_id_matches_definition(definition.game_id, request.game_id, "Observation request")

    if request.schema_version != ADAPTER_PAYLOAD_SCHEMA_VERSION:
        raise ValueError(
            (
                "Observation request schema_version "
                f"{request.schema_version!r} does not match "
                f"{ADAPTER_PAYLOAD_SCHEMA_VERSION!r}."
            )
        )


def _ensure_game_id_matches_definition(
    expected_game_id: str,
    actual_game_id: str,
    context: str,
) -> None:
    if actual_game_id != expected_game_id:
        raise ValueError(
            f"{context} game_id {actual_game_id!r} does not match {expected_game_id!r}."
        )


__all__: Sequence[str] = [
    "ADAPTER_PAYLOAD_SCHEMA_VERSION",
    "ActionResponsePayload",
    "DomainErrorPayload",
    "InProcessAgent",
    "ObservationRequestPayload",
    "PayloadPolicy",
    "TypedPayloadPolicyAdapter",
    "apply_payload_policy_turn",
    "build_observation_request",
    "dump_domain_error",
    "load_action_response",
]
