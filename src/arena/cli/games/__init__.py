"""CLI per-game adapters: renderers, input parsers, and config factories.

Each game registers an adapter at module import time. The adapter bundles the
pieces the CLI needs for that game so that the rest of ``arena.cli`` can
dispatch on ``game_id`` via a single registry instead of hand-maintained
if-ladders.

To add a new game's CLI surface, create ``arena/cli/games/<name>.py`` that
builds a :class:`CliGameAdapter` and calls :func:`register_cli_adapter`, then
import the module below so its top-level registration fires on package load.
"""

from __future__ import annotations

# Importing the per-game submodules fires their top-level register_cli_adapter()
# calls. Add new games here.
from arena.cli.games import connect4 as _connect4  # noqa: E402, F401
from arena.cli.games import nim as _nim  # noqa: E402, F401
from arena.cli.games import tictactoe as _tictactoe  # noqa: E402, F401
from arena.cli.games._registry import (
    CLI_GAME_ADAPTERS,
    CliGameAdapter,
    cli_game_ids,
    get_cli_adapter,
    register_cli_adapter,
)

__all__: tuple[str, ...] = (
    "CliGameAdapter",
    "CLI_GAME_ADAPTERS",
    "cli_game_ids",
    "get_cli_adapter",
    "register_cli_adapter",
)
