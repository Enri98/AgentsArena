"""MCP per-game adapter registry: action JSON schemas keyed on game_id.

Each game's MCP adapter module (``arena/mcp/games/<name>.py``) calls
:func:`register_mcp_adapter` at import time so that the MCP server can look up
the per-game action schema without a hand-maintained dispatch dict.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class McpGameAdapter:
    """Per-game MCP pieces."""

    game_id: str
    action_schema: dict[str, object]


MCP_GAME_ADAPTERS: dict[str, McpGameAdapter] = {}


def register_mcp_adapter(adapter: McpGameAdapter) -> None:
    """Register an MCP adapter for ``game_id``.

    Re-registration overwrites the previous entry.
    """

    MCP_GAME_ADAPTERS[adapter.game_id] = adapter


def get_mcp_adapter(game_id: str) -> McpGameAdapter:
    """Look up the MCP adapter for ``game_id`` or raise ``KeyError``."""

    return MCP_GAME_ADAPTERS[game_id]


def mcp_game_ids() -> tuple[str, ...]:
    """Return registered game_ids in insertion order."""

    return tuple(MCP_GAME_ADAPTERS.keys())


__all__: tuple[str, ...] = (
    "MCP_GAME_ADAPTERS",
    "McpGameAdapter",
    "get_mcp_adapter",
    "mcp_game_ids",
    "register_mcp_adapter",
)
