"""String templates for the game scaffold.

All templates use ``str.format``-style placeholders:

  - ``{{name}}``  → the lowercase game id (e.g. ``othello``)
  - ``{{Name}}``  → the PascalCase form (e.g. ``Othello``)
  - ``{{NAME}}``  → the upper-snake form (e.g. ``OTHELLO``)

Any literal ``{{`` or ``}}`` in the generated code is escaped here as ``{{{{``
or ``}}}}`` so ``str.format`` produces a single brace in the output.

The skeletons are intentionally minimal: ``rules.py`` raises
``NotImplementedError`` for every protocol method, payload models are
non-functional stubs, and adapters register a placeholder callable. The goal
is "imports cleanly, ruff-clean, and obviously a TODO" — not a playable game.
"""

from __future__ import annotations

GAME_INIT = '''\
"""{Name} domain models and rules implementation.

TODO: Implement the {name} game. See docs/ADDING_A_GAME.md for the walkthrough.
"""

from arena.games.{name}.actions import {Name}Action
from arena.games.{name}.config import {Name}Config
from arena.games.{name}.definition import (
    {NAME}_GAME_ID,
    {Name}GameDefinition,
    build_{name}_game_definition,
    register_{name},
)
from arena.games.{name}.events import {Name}MoveMade
from arena.games.{name}.observation import {Name}Observation
from arena.games.{name}.rules import {Name}RulesEngine
from arena.games.{name}.serializer import {Name}Serializer
from arena.games.{name}.state import {Name}State

__all__ = [
    "{NAME}_GAME_ID",
    "{Name}Action",
    "{Name}Config",
    "{Name}GameDefinition",
    "{Name}MoveMade",
    "{Name}Observation",
    "{Name}RulesEngine",
    "{Name}Serializer",
    "{Name}State",
    "build_{name}_game_definition",
    "register_{name}",
]
'''

GAME_CONFIG = '''\
"""Validated configuration for the {Name} game."""

from __future__ import annotations

from typing import Sequence

from pydantic import Field

from arena.core.config import BaseGameConfig


class {Name}Config(BaseGameConfig):
    """Boundary-facing configuration for {Name}.

    TODO: replace the stub field below with the real config surface.
    """

    placeholder: int = Field(default=1, ge=1)


__all__: Sequence[str] = ["{Name}Config"]
'''

GAME_STATE = '''\
"""Immutable {Name} game state.

TODO: replace the placeholder fields with the minimum authoritative state
required by the rules engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.types import Seat

VALID_SEATS = (0, 1)


@dataclass(frozen=True)
class {Name}State:
    """Minimal immutable state for a {Name} position."""

    current_seat: Seat

    def __post_init__(self) -> None:
        if type(self.current_seat) is not int or self.current_seat not in VALID_SEATS:
            raise ValueError("current_seat must be 0 or 1")


__all__: Sequence[str] = ["VALID_SEATS", "{Name}State"]
'''

GAME_ACTIONS = '''\
"""{Name} action model.

TODO: replace the placeholder action shape with the real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.actions import Action


@dataclass(frozen=True)
class {Name}Action(Action):
    """Placeholder {Name} action."""

    placeholder: int

    def __post_init__(self) -> None:
        if type(self.placeholder) is not int:
            raise ValueError("placeholder must be an int")


__all__: Sequence[str] = ["{Name}Action"]
'''

GAME_OBSERVATION = '''\
"""Player-facing {Name} observation model.

TODO: replace placeholder fields with the public game view for a seat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.observations import Observation
from arena.core.types import Seat
from arena.games.{name}.actions import {Name}Action


@dataclass(frozen=True)
class {Name}Observation(Observation):
    """Public {Name} observation for a seat."""

    current_seat: Seat
    legal_actions: tuple[{Name}Action, ...]


__all__: Sequence[str] = ["{Name}Observation"]
'''

GAME_EVENTS = '''\
"""{Name} domain events emitted by successful transitions.

TODO: add real event types describing what happened in each transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from arena.core.events import DomainEvent
from arena.core.types import Seat


@dataclass(frozen=True)
class {Name}MoveMade(DomainEvent):
    """Placeholder event emitted after a {name} move."""

    seat: Seat


__all__: Sequence[str] = ["{Name}MoveMade"]
'''

GAME_RULES = '''\
"""{Name} rules engine.

TODO: implement every protocol method. All methods currently raise
NotImplementedError so the package imports cleanly but any attempt to run a
match will surface the missing implementation immediately.
"""

from __future__ import annotations

from typing import Sequence

from arena.core.actions import Action
from arena.core.events import DomainEvent
from arena.core.results import RuleResult
from arena.core.rules_engine import TransitionResult
from arena.core.types import Seat
from arena.games.{name}.actions import {Name}Action
from arena.games.{name}.config import {Name}Config
from arena.games.{name}.observation import {Name}Observation
from arena.games.{name}.state import {Name}State


class {Name}RulesEngine:
    """Rules engine for {Name} — all methods are TODO stubs."""

    def __init__(self, config: {Name}Config | None = None) -> None:
        self._config = config or {Name}Config()

    def initial_state(self, config: {Name}Config) -> {Name}State:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.initial_state")

    def current_seat(self, state: {Name}State) -> Seat:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.current_seat")

    def legal_actions(self, state: {Name}State, seat: Seat) -> tuple[{Name}Action, ...]:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.legal_actions")

    def validate_action(self, state: {Name}State, seat: Seat, action: Action) -> None:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.validate_action")

    def apply_action(
        self,
        state: {Name}State,
        seat: Seat,
        action: {Name}Action,
    ) -> TransitionResult[{Name}State, DomainEvent, RuleResult | None]:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.apply_action")

    def is_terminal(self, state: {Name}State) -> bool:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.is_terminal")

    def result(self, state: {Name}State) -> RuleResult | None:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.result")

    def observation(self, state: {Name}State, seat: Seat) -> {Name}Observation:
        raise NotImplementedError("TODO: implement {Name}RulesEngine.observation")


__all__: Sequence[str] = ["{Name}RulesEngine"]
'''

GAME_SERIALIZER = '''\
"""Boundary serializers for {Name} config, actions, state, and observations.

TODO: flesh out payload models and round-trip logic. All dump_/load_ methods
currently raise NotImplementedError.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping


class {Name}ConfigPayload(BaseModel):
    """JSON-facing payload for {Name} configuration."""

    model_config = ConfigDict(extra="forbid", strict=True)

    placeholder: int = Field(default=1, ge=1)


class {Name}ActionPayload(BaseModel):
    """JSON-facing payload for {Name} actions."""

    model_config = ConfigDict(extra="forbid", strict=True)

    placeholder: int


class {Name}StatePayload(BaseModel):
    """JSON-facing payload for {Name} state snapshots."""

    model_config = ConfigDict(extra="forbid", strict=True)

    current_seat: int = Field(ge=0, le=1)


class {Name}ObservationPayload(BaseModel):
    """JSON-facing payload for {Name} observations."""

    model_config = ConfigDict(extra="forbid", strict=True)

    seat: int = Field(ge=0, le=1)
    current_seat: int = Field(ge=0, le=1)
    legal_actions: list[{Name}ActionPayload]


class {Name}Serializer:
    """Boundary serializer for {Name} domain models — TODO stubs."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        raise NotImplementedError("TODO: implement {Name}Serializer.dump_config")

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        raise NotImplementedError("TODO: implement {Name}Serializer.load_config")

    def dump_state(self, state: object) -> JSONMapping:
        raise NotImplementedError("TODO: implement {Name}Serializer.dump_state")

    def load_state(self, payload: JSONMapping) -> object:
        raise NotImplementedError("TODO: implement {Name}Serializer.load_state")

    def dump_action(self, action: object) -> JSONMapping:
        raise NotImplementedError("TODO: implement {Name}Serializer.dump_action")

    def load_action(self, payload: JSONMapping) -> object:
        raise NotImplementedError("TODO: implement {Name}Serializer.load_action")

    def dump_observation(self, observation: object) -> JSONMapping:
        raise NotImplementedError("TODO: implement {Name}Serializer.dump_observation")

    def load_observation(self, payload: JSONMapping) -> object:
        raise NotImplementedError("TODO: implement {Name}Serializer.load_observation")


__all__: Sequence[str] = [
    "{Name}ActionPayload",
    "{Name}ConfigPayload",
    "{Name}ObservationPayload",
    "{Name}Serializer",
    "{Name}StatePayload",
]
'''

GAME_DEFINITION = '''\
"""Registry-facing {Name} definition and registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.game_definition import GameDefinition
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.{name}.actions import {Name}Action
from arena.games.{name}.config import {Name}Config
from arena.games.{name}.observation import {Name}Observation
from arena.games.{name}.rules import {Name}RulesEngine
from arena.games.{name}.serializer import {Name}Serializer
from arena.games.{name}.state import {Name}State

{NAME}_GAME_ID = "{name}"


def build_{name}_game_definition() -> GameDefinition[
    {Name}Config,
    {Name}State,
    {Name}Action,
    {Name}Observation,
    RuleResult,
]:
    """Build the concrete registry-facing {Name} definition."""

    return GameDefinition(
        game_id={NAME}_GAME_ID,
        display_name="{Name}",
        config_type={Name}Config,
        state_type={Name}State,
        action_type={Name}Action,
        observation_type={Name}Observation,
        rules_engine={Name}RulesEngine(),
        serializer={Name}Serializer(),
        result_type=RuleResult,
    )


{Name}GameDefinition = build_{name}_game_definition()


def register_{name}(registry: GameRegistry) -> None:
    """Register {Name} in a supplied game registry."""

    registry.register({Name}GameDefinition)


__all__: Sequence[str] = [
    "{NAME}_GAME_ID",
    "{Name}GameDefinition",
    "build_{name}_game_definition",
    "register_{name}",
]
'''

CLI_ADAPTER = '''\
"""CLI adapter for {Name} — TODO stubs.

This module registers a placeholder :class:`CliGameAdapter` so the CLI
driver can dispatch on ``{NAME}_GAME_ID``. Replace the stub callables with
real implementations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.cli.games._registry import CliGameAdapter, register_cli_adapter
from arena.games.{name}.actions import {Name}Action
from arena.games.{name}.config import {Name}Config
from arena.games.{name}.definition import {NAME}_GAME_ID


def render_state(state_payload: Mapping[str, Any]) -> str:
    """Render the {Name} state as a colour terminal string. TODO."""
    raise NotImplementedError("TODO: implement {name} render_state")


def render_state_plain(state_payload: Mapping[str, Any]) -> str:
    """Render the {Name} state as plain text (no ANSI). TODO."""
    raise NotImplementedError("TODO: implement {name} render_state_plain")


def parse_input(line: str, observation: Any) -> {Name}Action | None:
    """Parse a human-typed move into a legal :class:`{Name}Action`. TODO."""
    raise NotImplementedError("TODO: implement {name} parse_input")


def _parse_scripted(spec: str) -> list[{Name}Action]:
    """Parse a comma-separated scripted-move spec. TODO."""
    raise NotImplementedError("TODO: implement {name} scripted parser")


def _config_from_args(args: Any) -> {Name}Config:
    """Build a :class:`{Name}Config` from argparse.Namespace. TODO."""
    raise NotImplementedError("TODO: implement {name} _config_from_args")


register_cli_adapter(
    CliGameAdapter(
        game_id={NAME}_GAME_ID,
        renderer=render_state,
        plain_renderer=render_state_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)


__all__: tuple[str, ...] = ("parse_input", "render_state", "render_state_plain")
'''

OLLAMA_ADAPTER = '''\
"""Ollama prompt builder for {Name} — TODO stubs."""

from __future__ import annotations

from typing import Any

from arena.agents.ollama._adapters import OllamaGameAdapter, register_ollama_adapter
from arena.games.{name}.definition import {NAME}_GAME_ID


class {Name}PromptBuilder:
    """Build Ollama chat messages and parse responses for {Name}. TODO."""

    SYSTEM_PROMPT = (
        "You are an expert {Name} player. "
        "TODO: describe the rules, the winning condition, and the response format."
    )

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]:
        raise NotImplementedError("TODO: implement {Name}PromptBuilder.build_messages")

    def parse_response(self, content: str, observation: Any) -> Any | None:
        raise NotImplementedError("TODO: implement {Name}PromptBuilder.parse_response")

    def format_spec(self) -> dict[str, Any]:
        raise NotImplementedError("TODO: implement {Name}PromptBuilder.format_spec")

    def describe_invalid(self, raw_content: str) -> str:
        return f"Response was not a valid legal action. Raw content: {{raw_content[:200]}}"


register_ollama_adapter(
    OllamaGameAdapter(
        game_id={NAME}_GAME_ID,
        prompt_builder_factory={Name}PromptBuilder,
    )
)


__all__: tuple[str, ...] = ("{Name}PromptBuilder",)
'''

MCP_ADAPTER = '''\
"""MCP adapter registration for {Name} — TODO stub."""

from __future__ import annotations

from arena.games.{name}.definition import {NAME}_GAME_ID
from arena.mcp._adapters import McpGameAdapter, register_mcp_adapter

# TODO: fill in the JSON schema describing a {Name} action payload.
{NAME}_ACTION_SCHEMA: dict[str, object] = {{}}


register_mcp_adapter(
    McpGameAdapter(
        game_id={NAME}_GAME_ID,
        action_schema={NAME}_ACTION_SCHEMA,
    )
)


__all__: tuple[str, ...] = ("{NAME}_ACTION_SCHEMA",)
'''


__all__: tuple[str, ...] = (
    "CLI_ADAPTER",
    "GAME_ACTIONS",
    "GAME_CONFIG",
    "GAME_DEFINITION",
    "GAME_EVENTS",
    "GAME_INIT",
    "GAME_OBSERVATION",
    "GAME_RULES",
    "GAME_SERIALIZER",
    "GAME_STATE",
    "MCP_ADAPTER",
    "OLLAMA_ADAPTER",
)
