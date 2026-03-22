"""Tests for the Connect 4 config model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.config import BaseGameConfig
from arena.games.connect4 import Connect4Config


def test_connect4_config_is_importable_and_uses_the_shared_base_model() -> None:
    config = Connect4Config()

    assert Connect4Config.__name__ == "Connect4Config"
    assert isinstance(config, BaseGameConfig)


def test_connect4_config_exposes_the_standard_defaults() -> None:
    config = Connect4Config()

    assert config.rows == 6
    assert config.columns == 7
    assert config.connect_length == 4


def test_connect4_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Connect4Config(rows=6, columns=7, connect_length=4, seats=2)


def test_connect4_config_uses_strict_validation() -> None:
    with pytest.raises(ValidationError):
        Connect4Config(rows="6")


@pytest.mark.parametrize("field_name, value", [("rows", 3), ("columns", 3), ("connect_length", 1)])
def test_connect4_config_rejects_values_below_supported_minimum(
    field_name: str,
    value: int,
) -> None:
    payload = {"rows": 6, "columns": 7, "connect_length": 4}
    payload[field_name] = value

    with pytest.raises(ValidationError):
        Connect4Config(**payload)


def test_connect4_config_rejects_connect_length_larger_than_the_board() -> None:
    with pytest.raises(ValidationError):
        Connect4Config(rows=4, columns=5, connect_length=6)
