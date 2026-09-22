"""Shared game-definition metadata and wiring contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.observations import Observation
from arena.core.results import RuleResult
from arena.core.rules_engine import RulesEngine
from arena.core.serializer import Serializer

ConfigModelT = TypeVar("ConfigModelT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
ResultT = TypeVar("ResultT", bound=RuleResult)


@dataclass(frozen=True)
class GameDefinition(Generic[ConfigModelT, StateT, ActionT, ObservationT, ResultT]):
    """Registry-facing metadata and shared wiring for a concrete game."""

    game_id: str
    display_name: str
    config_type: type[ConfigModelT]
    state_type: type[StateT]
    action_type: type[ActionT]
    observation_type: type[ObservationT]
    rules_engine: RulesEngine[ConfigModelT, StateT, ActionT, ObservationT]
    serializer: Serializer
    result_type: type[ResultT]

    #: Whether seats see different information (Phase 36 Slice 1).
    #: ``False`` means the public view is the full state, which is what makes
    #: the spectator channel safe to serve from ``dump_state``. A game setting
    #: this to ``True`` must implement the redaction hooks in
    #: ``arena.core.public_view``; ``GameRegistry.register`` enforces that.
    has_hidden_information: bool = False

    #: Whether the game has chance nodes — points where no seat acts and the
    #: rules engine resolves a random outcome (Phase 37). A game setting this
    #: must implement the hooks in ``arena.core.chance``; ``GameRegistry.register``
    #: enforces that. Randomness must live in serialized state as a ``ChanceRng``,
    #: never in config: config is broadcast to both seats and embedded in every
    #: snapshot, so a seed placed there is public.
    has_chance_nodes: bool = False


__all__: Sequence[str] = ["GameDefinition"]
