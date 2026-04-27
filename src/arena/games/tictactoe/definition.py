"""Registry-facing Tic-Tac-Toe definition and registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.game_definition import GameDefinition
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult
from arena.games.tictactoe.actions import PlaceMark
from arena.games.tictactoe.config import TicTacToeConfig
from arena.games.tictactoe.observation import TicTacToeObservation
from arena.games.tictactoe.rules import TicTacToeRulesEngine
from arena.games.tictactoe.serializer import TicTacToeSerializer
from arena.games.tictactoe.state import TicTacToeState

TICTACTOE_GAME_ID = "tictactoe"


def build_tictactoe_game_definition() -> GameDefinition[
    TicTacToeConfig,
    TicTacToeState,
    PlaceMark,
    TicTacToeObservation,
    RuleResult,
]:
    """Build the concrete registry-facing Tic-Tac-Toe definition."""

    return GameDefinition(
        game_id=TICTACTOE_GAME_ID,
        display_name="Tic-Tac-Toe",
        config_type=TicTacToeConfig,
        state_type=TicTacToeState,
        action_type=PlaceMark,
        observation_type=TicTacToeObservation,
        rules_engine=TicTacToeRulesEngine(),
        serializer=TicTacToeSerializer(),
        result_type=RuleResult,
    )


TicTacToeGameDefinition = build_tictactoe_game_definition()


def register_tictactoe(registry: GameRegistry) -> None:
    """Register Tic-Tac-Toe in a supplied game registry."""

    registry.register(TicTacToeGameDefinition)


__all__: Sequence[str] = [
    "TICTACTOE_GAME_ID",
    "TicTacToeGameDefinition",
    "build_tictactoe_game_definition",
    "register_tictactoe",
]
