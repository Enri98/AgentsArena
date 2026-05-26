"""Ollama per-game adapter registry: prompt-builder factories keyed on game_id.

Each game's prompt-builder module (``arena/agents/ollama/<name>.py``) calls
:func:`register_ollama_adapter` at import time. The remote helper and CLI
driver then look up the factory by ``game_id`` instead of hand-maintaining an
if-ladder.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from arena.agents.ollama.agent import PromptBuilder


@dataclass(frozen=True)
class OllamaGameAdapter:
    """Per-game pieces required to drive an Ollama-backed seat."""

    game_id: str
    prompt_builder_factory: Callable[[], PromptBuilder]


OLLAMA_GAME_ADAPTERS: dict[str, OllamaGameAdapter] = {}


def register_ollama_adapter(adapter: OllamaGameAdapter) -> None:
    """Register an Ollama adapter for ``game_id``.

    Re-registration overwrites the previous entry.
    """

    OLLAMA_GAME_ADAPTERS[adapter.game_id] = adapter


def get_ollama_adapter(game_id: str) -> OllamaGameAdapter:
    """Look up the Ollama adapter for ``game_id`` or raise ``KeyError``."""

    return OLLAMA_GAME_ADAPTERS[game_id]


def ollama_game_ids() -> tuple[str, ...]:
    """Return registered game_ids in insertion order."""

    return tuple(OLLAMA_GAME_ADAPTERS.keys())


__all__: tuple[str, ...] = (
    "OLLAMA_GAME_ADAPTERS",
    "OllamaGameAdapter",
    "get_ollama_adapter",
    "ollama_game_ids",
    "register_ollama_adapter",
)
