"""Tests for the Tic-Tac-Toe config model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.config import BaseGameConfig
from arena.games.tictactoe import TicTacToeConfig


def test_tictactoe_config_is_importable_and_uses_the_shared_base_model() -> None:
    config = TicTacToeConfig()

    assert TicTacToeConfig.__name__ == "TicTacToeConfig"
    assert isinstance(config, BaseGameConfig)


def test_tictactoe_config_exposes_the_standard_defaults() -> None:
    config = TicTacToeConfig()

    assert config.rows == 3
    assert config.columns == 3
    assert config.connect_length == 3


def test_tictactoe_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TicTacToeConfig(rows=3, columns=3, connect_length=3, seats=2)


def test_tictactoe_config_uses_strict_validation() -> None:
    with pytest.raises(ValidationError):
        TicTacToeConfig(rows="3")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("rows", 4), ("columns", 4), ("connect_length", 2)],
)
def test_tictactoe_config_rejects_non_standard_values(
    field_name: str,
    value: int,
) -> None:
    payload = {"rows": 3, "columns": 3, "connect_length": 3}
    payload[field_name] = value

    with pytest.raises(ValidationError):
        TicTacToeConfig(**payload)
