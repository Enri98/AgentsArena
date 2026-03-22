"""Tests for shared core config models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.config import BaseGameConfig


class ExampleConfig(BaseGameConfig):
    """Trivial config subclass used to verify base-model behavior."""

    rows: int


def test_base_config_model_is_importable() -> None:
    assert BaseGameConfig.__name__ == "BaseGameConfig"


def test_base_config_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ExampleConfig(rows=6, columns=7)


def test_base_config_uses_strict_validation_without_coercion() -> None:
    with pytest.raises(ValidationError):
        ExampleConfig(rows="6")


def test_base_config_still_requires_subclass_fields() -> None:
    with pytest.raises(ValidationError):
        ExampleConfig()


def test_base_config_subclass_can_generate_json_schema() -> None:
    schema = ExampleConfig.model_json_schema()

    assert schema["title"] == "ExampleConfig"
    assert schema["properties"]["rows"]["type"] == "integer"
    assert schema["required"] == ["rows"]
