"""Ollama-backed local LLM agent package."""

from arena.agents.ollama.agent import OllamaAgent, PromptBuilder
from arena.agents.ollama.client import OllamaClient
from arena.agents.ollama.connect4 import Connect4PromptBuilder
from arena.agents.ollama.exceptions import (
    OllamaIllegalActionError,
    OllamaModelMissingError,
    OllamaServerError,
    OllamaUnavailableError,
)
from arena.agents.ollama.probe import probe_models
from arena.agents.ollama.tictactoe import TicTacToePromptBuilder

__all__: tuple[str, ...] = (
    "Connect4PromptBuilder",
    "OllamaAgent",
    "OllamaClient",
    "OllamaIllegalActionError",
    "OllamaModelMissingError",
    "OllamaServerError",
    "OllamaUnavailableError",
    "PromptBuilder",
    "TicTacToePromptBuilder",
    "probe_models",
)
