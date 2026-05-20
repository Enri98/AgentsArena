"""Registry-facing Nim definition and registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.game_definition import GameDefinition
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.nim.actions import TakeObjects
from arena.games.nim.config import NimConfig
from arena.games.nim.observation import NimObservation
from arena.games.nim.rules import NimRulesEngine
from arena.games.nim.serializer import NimSerializer
from arena.games.nim.state import NimState

NIM_GAME_ID = "nim"


def build_nim_game_definition() -> GameDefinition[
    NimConfig,
    NimState,
    TakeObjects,
    NimObservation,
    RuleResult,
]:
    """Build the concrete registry-facing Nim definition."""

    return GameDefinition(
        game_id=NIM_GAME_ID,
        display_name="Nim",
        config_type=NimConfig,
        state_type=NimState,
        action_type=TakeObjects,
        observation_type=NimObservation,
        rules_engine=NimRulesEngine(),
        serializer=NimSerializer(),
        result_type=RuleResult,
    )


NimGameDefinition = build_nim_game_definition()


def register_nim(registry: GameRegistry) -> None:
    """Register Nim in a supplied game registry."""

    registry.register(NimGameDefinition)


__all__: Sequence[str] = [
    "NIM_GAME_ID",
    "NimGameDefinition",
    "build_nim_game_definition",
    "register_nim",
]
