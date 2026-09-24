"""Registry-facing Pig definition and registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.game_definition import GameDefinition
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.pig.actions import PigMove
from arena.games.pig.config import PigConfig
from arena.games.pig.observation import PigObservation
from arena.games.pig.rules import PigRulesEngine
from arena.games.pig.serializer import PigSerializer
from arena.games.pig.state import PigState

PIG_GAME_ID = "pig"


def build_pig_game_definition() -> GameDefinition[
    PigConfig,
    PigState,
    PigMove,
    PigObservation,
    RuleResult,
]:
    """Build the concrete registry-facing Pig definition."""

    return GameDefinition(
        game_id=PIG_GAME_ID,
        display_name="Pig",
        config_type=PigConfig,
        state_type=PigState,
        action_type=PigMove,
        observation_type=PigObservation,
        rules_engine=PigRulesEngine(),
        serializer=PigSerializer(),
        result_type=RuleResult,
        has_chance_nodes=True,
    )


PigGameDefinition = build_pig_game_definition()


def register_pig(registry: GameRegistry) -> None:
    """Register Pig in a supplied game registry."""

    registry.register(PigGameDefinition)


__all__: Sequence[str] = [
    "PIG_GAME_ID",
    "PigGameDefinition",
    "build_pig_game_definition",
    "register_pig",
]
