"""Ollama-backed local LLM agent package."""

from arena.agents.ollama._remote import run_remote_seat
from arena.agents.ollama.agent import OllamaAgent, PromptBuilder
from arena.agents.ollama.client import OllamaClient

# Importing the per-game prompt-builder modules before _remote ensures their
# top-level register_ollama_adapter() calls populate the adapter registry by
# the time _remote (which consults it) is initialised.
from arena.agents.ollama.connect4 import Connect4PromptBuilder
from arena.agents.ollama.exceptions import (
    OllamaIllegalActionError,
    OllamaModelMissingError,
    OllamaServerError,
    OllamaUnavailableError,
)
from arena.agents.ollama.nim import NimPromptBuilder
from arena.agents.ollama.probe import probe_models
from arena.agents.ollama.tictactoe import TicTacToePromptBuilder

__all__: tuple[str, ...] = (
    "Connect4PromptBuilder",
    "NimPromptBuilder",
    "OllamaAgent",
    "OllamaClient",
    "OllamaIllegalActionError",
    "OllamaModelMissingError",
    "OllamaServerError",
    "OllamaUnavailableError",
    "PromptBuilder",
    "TicTacToePromptBuilder",
    "probe_models",
    "run_remote_seat",
)
