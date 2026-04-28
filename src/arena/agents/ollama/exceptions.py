"""Typed exceptions for Ollama-backed agent failures."""

from __future__ import annotations

from collections.abc import Sequence


class OllamaUnavailableError(Exception):
    """Raised when the Ollama daemon cannot be reached."""

    def __init__(self, host: str, cause_message: str) -> None:
        self.host = host
        self.cause_message = cause_message

    def __str__(self) -> str:
        return f"Ollama daemon at {self.host!r} is unreachable: {self.cause_message}"


class OllamaModelMissingError(Exception):
    """Raised when one or more required models are not available in the Ollama daemon."""

    def __init__(
        self,
        host: str,
        missing_models: Sequence[str],
        available_models: Sequence[str],
    ) -> None:
        self.host = host
        self.missing_models = list(missing_models)
        self.available_models = list(available_models)

    def __str__(self) -> str:
        missing = ", ".join(repr(m) for m in self.missing_models)
        available = ", ".join(repr(m) for m in self.available_models) or "(none)"
        return (
            f"Models {missing} not found at {self.host!r}. "
            f"Available: {available}. Run `ollama pull <model>` to install."
        )


class OllamaServerError(Exception):
    """Raised when the Ollama daemon returns a non-2xx HTTP response."""

    def __init__(self, host: str, status: int, body_message: str) -> None:
        self.host = host
        self.status = status
        self.body_message = body_message

    def __str__(self) -> str:
        return (
            f"Ollama daemon at {self.host!r} returned HTTP {self.status}: "
            f"{self.body_message}"
        )


class OllamaIllegalActionError(Exception):
    """Raised when an Ollama model exhausts its retry budget without producing a legal action."""

    def __init__(self, model: str, last_attempt: str, attempts: int) -> None:
        self.model = model
        self.last_attempt = last_attempt
        self.attempts = attempts

    def __str__(self) -> str:
        return (
            f"Model {self.model!r} failed to produce a legal action after "
            f"{self.attempts} attempt(s). Last attempt: {self.last_attempt!r}"
        )


__all__: tuple[str, ...] = (
    "OllamaIllegalActionError",
    "OllamaModelMissingError",
    "OllamaServerError",
    "OllamaUnavailableError",
)
