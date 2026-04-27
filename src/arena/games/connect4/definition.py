"""Registry-facing Connect 4 definition and registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.game_definition import GameDefinition
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.connect4.actions import DropDisc
from arena.games.connect4.config import Connect4Config
from arena.games.connect4.observation import Connect4Observation
from arena.games.connect4.rules import Connect4RulesEngine
from arena.games.connect4.serializer import Connect4Serializer
from arena.games.connect4.state import Connect4State

CONNECT4_GAME_ID = "connect4"


def build_connect4_game_definition() -> GameDefinition[
    Connect4Config,
    Connect4State,
    DropDisc,
    Connect4Observation,
    RuleResult,
]:
    """Build the concrete registry-facing Connect 4 definition."""

    return GameDefinition(
        game_id=CONNECT4_GAME_ID,
        display_name="Connect 4",
        config_type=Connect4Config,
        state_type=Connect4State,
        action_type=DropDisc,
        observation_type=Connect4Observation,
        rules_engine=Connect4RulesEngine(),
        serializer=Connect4Serializer(),
        result_type=RuleResult,
    )


Connect4GameDefinition = build_connect4_game_definition()


def register_connect4(registry: GameRegistry) -> None:
    """Register Connect 4 in a supplied game registry."""

    registry.register(Connect4GameDefinition)


__all__: Sequence[str] = [
    "CONNECT4_GAME_ID",
    "Connect4GameDefinition",
    "build_connect4_game_definition",
    "register_connect4",
]
