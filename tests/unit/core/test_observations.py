"""Tests for shared observation abstractions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from arena.core.observations import Observation


@dataclass(frozen=True)
class ExampleObservation(Observation):
    visible_cells: tuple[int, ...]


def test_observation_exposes_a_stable_type_identifier() -> None:
    observation = ExampleObservation(seat=1, visible_cells=(0, 1))

    assert observation.observation_type == "ExampleObservation"


def test_observation_instances_are_immutable() -> None:
    observation = ExampleObservation(seat=1, visible_cells=(0, 1))

    with pytest.raises(FrozenInstanceError):
        observation.seat = 0
