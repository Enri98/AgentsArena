"""CLI per-game adapter dataclass and module-level registry.

Lives in a separate module from ``arena.cli.games`` so per-game adapter
submodules (``arena/cli/games/<name>.py``) can import the registry without
causing a circular import when ``arena.cli.games.__init__`` imports them in
turn to fire registration.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arena.core.actions import Action
from arena.core.config import BaseGameConfig

# argparse.Namespace is stdlib but we keep the annotation loose to avoid a
# hard dependency in the dataclass module path.
ConfigFactory = Callable[[Any], BaseGameConfig]
HumanParser = Callable[[str, Any], Action | None]
ScriptedParser = Callable[[str], list[Action]]
StateRenderer = Callable[[Mapping[str, Any]], str]


@dataclass(frozen=True)
class CliGameAdapter:
    """Per-game CLI pieces (renderers, parsers, config factory).

    All fields are required for a game to be playable via the CLI driver.
    Games that are headless-only need not register an adapter at all.
    """

    game_id: str
    renderer: StateRenderer
    plain_renderer: StateRenderer
    human_parser: HumanParser
    scripted_parser: ScriptedParser
    config_factory: ConfigFactory


CLI_GAME_ADAPTERS: dict[str, CliGameAdapter] = {}


def register_cli_adapter(adapter: CliGameAdapter) -> None:
    """Register a CLI adapter for the given ``game_id``.

    Re-registration of the same ``game_id`` overwrites the previous entry,
    matching the historical behaviour of the dict-based dispatch tables.
    """

    CLI_GAME_ADAPTERS[adapter.game_id] = adapter


def get_cli_adapter(game_id: str) -> CliGameAdapter:
    """Look up the CLI adapter for ``game_id`` or raise ``KeyError``."""

    return CLI_GAME_ADAPTERS[game_id]


def cli_game_ids() -> tuple[str, ...]:
    """Return the registered game_ids in insertion order."""

    return tuple(CLI_GAME_ADAPTERS.keys())


__all__: tuple[str, ...] = (
    "CliGameAdapter",
    "CLI_GAME_ADAPTERS",
    "cli_game_ids",
    "get_cli_adapter",
    "register_cli_adapter",
)
