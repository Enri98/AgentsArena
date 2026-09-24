"""probe_models resolves untagged names the way Ollama does."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arena.agents.ollama.exceptions import OllamaModelMissingError
from arena.agents.ollama.probe import probe_models


def _client(tags: list[str]):
    return SimpleNamespace(list_tags=lambda: tags)


def test_an_untagged_name_matches_its_latest_tag() -> None:
    installed = _client(["llama3.2:latest", "qwen2.5:1.5b"])
    probe_models("h", ["llama3.2", "qwen2.5:1.5b"], client=installed)


def test_a_missing_model_is_still_reported() -> None:
    with pytest.raises(OllamaModelMissingError):
        probe_models("h", ["mistral"], client=_client(["llama3.2:latest"]))
    with pytest.raises(OllamaModelMissingError):
        probe_models("h", ["llama3.2:1b"], client=_client(["llama3.2:latest"]))
