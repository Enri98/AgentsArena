"""Tests for the Pig config model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.config import BaseGameConfig
from arena.games.pig import DEFAULT_TARGET_SCORE, PigConfig


def test_defaults() -> None:
    config = PigConfig()
    assert isinstance(config, BaseGameConfig)
    assert config.target_score == DEFAULT_TARGET_SCORE == 50


@pytest.mark.parametrize("target", [0, -5, 1001])
def test_out_of_range_targets_are_rejected(target: int) -> None:
    with pytest.raises(ValidationError):
        PigConfig(target_score=target)


def test_config_has_no_seed_field() -> None:
    """Config is broadcast, so a seed in it would be public."""

    assert "seed" not in PigConfig.model_fields
    with pytest.raises(ValidationError):
        PigConfig(seed=1)  # type: ignore[call-arg]
