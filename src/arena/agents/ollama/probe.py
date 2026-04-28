"""Model availability probe for Ollama startup validation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from arena.agents.ollama.client import OllamaClient
from arena.agents.ollama.exceptions import OllamaModelMissingError

if TYPE_CHECKING:
    pass


def probe_models(
    host: str,
    required: Sequence[str],
    *,
    client: OllamaClient | None = None,
) -> None:
    """Verify that all required models are available on the Ollama daemon.

    Raises OllamaUnavailableError if the daemon cannot be reached.
    Raises OllamaModelMissingError if any required model is absent.
    """

    resolved_client = client if client is not None else OllamaClient(host)
    available = resolved_client.list_tags()
    missing = [m for m in required if m not in available]
    if missing:
        raise OllamaModelMissingError(
            host=host,
            missing_models=missing,
            available_models=available,
        )


__all__: tuple[str, ...] = ("probe_models",)
