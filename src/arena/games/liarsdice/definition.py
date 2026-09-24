"""Registry-facing Liar's Dice definition and registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.game_definition import GameDefinition
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.liarsdice.actions import LiarsDiceAction
from arena.games.liarsdice.config import LiarsDiceConfig
from arena.games.liarsdice.observation import LiarsDiceObservation
from arena.games.liarsdice.rules import LiarsDiceRulesEngine
from arena.games.liarsdice.serializer import LiarsDiceSerializer
from arena.games.liarsdice.state import LiarsDiceState

LIARSDICE_GAME_ID = "liarsdice"


def build_liarsdice_game_definition() -> GameDefinition[
    LiarsDiceConfig,
    LiarsDiceState,
    LiarsDiceAction,
    LiarsDiceObservation,
    RuleResult,
]:
    """Build the concrete registry-facing Liar's Dice definition."""

    return GameDefinition(
        game_id=LIARSDICE_GAME_ID,
        display_name="Liar's Dice",
        config_type=LiarsDiceConfig,
        state_type=LiarsDiceState,
        action_type=LiarsDiceAction,
        observation_type=LiarsDiceObservation,
        rules_engine=LiarsDiceRulesEngine(),
        serializer=LiarsDiceSerializer(),
        result_type=RuleResult,
        has_hidden_information=True,
        has_chance_nodes=True,
    )


LiarsDiceGameDefinition = build_liarsdice_game_definition()


def register_liarsdice(registry: GameRegistry) -> None:
    """Register Liar's Dice in a supplied game registry."""

    registry.register(LiarsDiceGameDefinition)


__all__: Sequence[str] = [
    "LIARSDICE_GAME_ID",
    "LiarsDiceGameDefinition",
    "build_liarsdice_game_definition",
    "register_liarsdice",
]
