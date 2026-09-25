"""Registry-facing Rps definition and registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.game_definition import GameDefinition
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.rps.actions import Throw
from arena.games.rps.config import RpsConfig
from arena.games.rps.observation import RpsObservation
from arena.games.rps.rules import RpsRulesEngine
from arena.games.rps.serializer import RpsSerializer
from arena.games.rps.state import RpsState

RPS_GAME_ID = "rps"


def build_rps_game_definition() -> GameDefinition[
    RpsConfig,
    RpsState,
    Throw,
    RpsObservation,
    RuleResult,
]:
    """Build the concrete registry-facing Rps definition."""

    return GameDefinition(
        game_id=RPS_GAME_ID,
        display_name="Rock-Paper-Scissors",
        config_type=RpsConfig,
        state_type=RpsState,
        action_type=Throw,
        observation_type=RpsObservation,
        rules_engine=RpsRulesEngine(),
        serializer=RpsSerializer(),
        result_type=RuleResult,
        # Both seats throw at once every round (Phase 41).
        has_simultaneous_moves=True,
    )


RpsGameDefinition = build_rps_game_definition()


def register_rps(registry: GameRegistry) -> None:
    """Register Rps in a supplied game registry."""

    registry.register(RpsGameDefinition)


__all__: Sequence[str] = [
    "RPS_GAME_ID",
    "RpsGameDefinition",
    "build_rps_game_definition",
    "register_rps",
]
