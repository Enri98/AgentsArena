"""Connect 4 domain models and rules implementation."""

from arena.games.connect4.actions import DropDisc
from arena.games.connect4.config import Connect4Config
from arena.games.connect4.definition import (
    CONNECT4_GAME_ID,
    Connect4GameDefinition,
    build_connect4_game_definition,
    register_connect4,
)
from arena.games.connect4.events import DiscDropped, GameDrawn, WinnerDetected
from arena.games.connect4.observation import Connect4Observation
from arena.games.connect4.rules import Connect4RulesEngine
from arena.games.connect4.serializer import Connect4Serializer
from arena.games.connect4.state import (
    EMPTY_CELL,
    SEAT0_DISC,
    SEAT1_DISC,
    Connect4Board,
    Connect4State,
    disc_for_seat,
)

__all__ = [
    "EMPTY_CELL",
    "SEAT0_DISC",
    "SEAT1_DISC",
    "Connect4Board",
    "Connect4Config",
    "CONNECT4_GAME_ID",
    "Connect4GameDefinition",
    "Connect4Observation",
    "Connect4RulesEngine",
    "Connect4Serializer",
    "Connect4State",
    "DiscDropped",
    "DropDisc",
    "GameDrawn",
    "WinnerDetected",
    "build_connect4_game_definition",
    "disc_for_seat",
    "register_connect4",
]
