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


__all__: Sequence[str] = ["GameDefinition"]
