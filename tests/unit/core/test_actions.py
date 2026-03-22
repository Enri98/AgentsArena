"""Tests for shared action abstractions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from arena.core.actions import Action


@dataclass(frozen=True)
class ExampleAction(Action):
    column: int


def test_action_exposes_a_stable_type_identifier() -> None:
    action = ExampleAction(column=2)

    assert action.action_type == "ExampleAction"


def test_action_instances_are_immutable() -> None:
    action = ExampleAction(column=2)

    with pytest.raises(FrozenInstanceError):
        action.column = 3
