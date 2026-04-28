"""Generic Ollama-backed typed agent with retry-with-feedback loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from arena.agents.ollama.client import OllamaClient
from arena.agents.ollama.exceptions import OllamaIllegalActionError

ObservationT = TypeVar("ObservationT")
ActionT = TypeVar("ActionT")


class PromptBuilder(Protocol):
    """Interface for game-specific prompt construction and response parsing."""

    def build_messages(
        self,
        observation: Any,
        retry_feedback: tuple[str, ...] = (),
    ) -> list[dict[str, str]]: ...

    def parse_response(self, content: str, observation: Any) -> Any | None: ...

    def format_spec(self) -> dict[str, Any]: ...

    def describe_invalid(self, raw_content: str) -> str: ...


@dataclass
class OllamaAgent(Generic[ObservationT, ActionT]):
    """Typed in-process agent backed by a local Ollama model."""

    client: OllamaClient
    model: str
    prompt_builder: PromptBuilder
    max_retries: int = 3
    seed: int = 0
    temperature: float = 0.0
    retry_callback: Callable[[int, str], None] | None = None
    decision_callback: Callable[[int, str], None] | None = None
    use_format_spec: bool = True

    def select_action(self, observation: Any) -> Any:
        """Run the retry loop and return the first legal action from the model."""

        feedback: list[str] = []

        for attempt in range(self.max_retries + 1):
            messages = self.prompt_builder.build_messages(observation, tuple(feedback))
            response = self.client.chat(
                self.model,
                messages,
                self.prompt_builder.format_spec() if self.use_format_spec else None,
                self.seed,
                self.temperature,
            )
            content: str = response["message"]["content"]
            parsed = self.prompt_builder.parse_response(content, observation)

            if parsed is not None and parsed in observation.legal_actions:
                if self.decision_callback is not None:
                    self.decision_callback(attempt + 1, _extract_thought(content))
                return parsed

            if parsed is None:
                reason = self.prompt_builder.describe_invalid(content)
            else:
                reason = (
                    f"Action {parsed!r} is not legal. "
                    f"Legal actions: {list(observation.legal_actions)}"
                )

            feedback.append(reason)

            if attempt < self.max_retries:
                if self.retry_callback is not None:
                    self.retry_callback(attempt + 1, reason)

        last_attempt = feedback[-1] if feedback else ""
        raise OllamaIllegalActionError(
            model=self.model,
            last_attempt=last_attempt,
            attempts=self.max_retries + 1,
        )


def _extract_thought(content: str) -> str:
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return ""
    if not isinstance(parsed, dict):
        return ""
    thought = parsed.get("thought", "")
    return thought if isinstance(thought, str) else ""


__all__: tuple[str, ...] = ("OllamaAgent", "PromptBuilder")
