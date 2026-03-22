"""Shared serializer contracts for simulation-boundary payloads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Protocol, TypeAlias, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from arena.core.config import BaseGameConfig

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JsonValue
JSONMapping: TypeAlias = dict[str, JsonValue]


class SnapshotEnvelope(BaseModel):
    """Stable JSON-friendly envelope for serialized state snapshots."""

    model_config = ConfigDict(extra="forbid", strict=True)

    game_id: str
    schema_version: Annotated[int, Field(ge=1)]
    config: JSONMapping
    state: JSONMapping


@runtime_checkable
class Serializer(Protocol):
    """Shared serializer interface for game boundary payloads."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        """Serialize a validated config model to a JSON-friendly payload."""

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        """Rehydrate a validated config model from a JSON-friendly payload."""

    def dump_state(self, state: object) -> JSONMapping:
        """Serialize in-memory game state to a JSON-friendly payload."""

    def load_state(self, payload: JSONMapping) -> object:
        """Rehydrate in-memory game state from a JSON-friendly payload."""

    def dump_action(self, action: object) -> JSONMapping:
        """Serialize an in-memory action to a JSON-friendly payload."""

    def load_action(self, payload: JSONMapping) -> object:
        """Rehydrate an in-memory action from a JSON-friendly payload."""

    def dump_observation(self, observation: object) -> JSONMapping:
        """Serialize an in-memory observation to a JSON-friendly payload."""

    def load_observation(self, payload: JSONMapping) -> object:
        """Rehydrate an in-memory observation from a JSON-friendly payload."""


__all__: Sequence[str] = [
    "JSONMapping",
    "JSONPrimitive",
    "JSONValue",
    "Serializer",
    "SnapshotEnvelope",
]
