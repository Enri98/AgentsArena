"""Tic-Tac-Toe domain models and rules implementation."""

from arena.games.tictactoe.actions import PlaceMark
from arena.games.tictactoe.config import TicTacToeConfig
from arena.games.tictactoe.definition import (
    TICTACTOE_GAME_ID,
    TicTacToeGameDefinition,
    build_tictactoe_game_definition,
    register_tictactoe,
)
from arena.games.tictactoe.events import GameDrawn, MarkPlaced, WinnerDetected
from arena.games.tictactoe.observation import TicTacToeObservation
from arena.games.tictactoe.rules import TicTacToeRulesEngine
from arena.games.tictactoe.serializer import TicTacToeSerializer
from arena.games.tictactoe.state import (
    EMPTY_CELL,
    SEAT0_MARK,
    SEAT1_MARK,
    TicTacToeBoard,
    TicTacToeState,
    mark_for_seat,
)

__all__ = [
    "EMPTY_CELL",
    "SEAT0_MARK",
    "SEAT1_MARK",
    "PlaceMark",
    "TICTACTOE_GAME_ID",
    "TicTacToeBoard",
    "TicTacToeConfig",
    "TicTacToeGameDefinition",
    "TicTacToeObservation",
    "TicTacToeRulesEngine",
    "TicTacToeSerializer",
    "TicTacToeState",
    "GameDrawn",
    "MarkPlaced",
    "WinnerDetected",
    "build_tictactoe_game_definition",
    "mark_for_seat",
    "register_tictactoe",
]
