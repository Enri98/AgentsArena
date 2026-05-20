"""Tests for the Nim config model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.config import BaseGameConfig
from arena.games.nim import NimConfig


def test_nim_config_is_importable_and_uses_shared_base_model() -> None:
    config = NimConfig()

    assert NimConfig.__name__ == "NimConfig"
    assert isinstance(config, BaseGameConfig)


def test_nim_config_has_correct_defaults() -> None:
    config = NimConfig()

    assert config.num_piles == 3
    assert config.max_pile_size == 7


def test_nim_config_accepts_custom_valid_values() -> None:
    config = NimConfig(num_piles=5, max_pile_size=10)

    assert config.num_piles == 5
    assert config.max_pile_size == 10


def test_nim_config_rejects_zero_num_piles() -> None:
    with pytest.raises(ValidationError):
        NimConfig(num_piles=0)


def test_nim_config_rejects_zero_max_pile_size() -> None:
    with pytest.raises(ValidationError):
        NimConfig(max_pile_size=0)


def test_nim_config_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        NimConfig(num_piles=-1)

    with pytest.raises(ValidationError):
        NimConfig(max_pile_size=-1)


def test_nim_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        NimConfig(num_piles=3, max_pile_size=7, extra_field=True)


def test_nim_config_rejects_non_integer_values() -> None:
    with pytest.raises(ValidationError):
        NimConfig(num_piles="3")
