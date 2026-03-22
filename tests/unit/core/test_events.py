"""Tests for core domain event abstractions."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from arena.core.events import DomainEvent
from arena.core.types import Seat


@dataclass(frozen=True)
class DiscDropped(DomainEvent):
    seat: Seat
    column: int


def test_domain_event_base_is_importable() -> None:
    assert DomainEvent.__name__ == "DomainEvent"


def test_domain_event_subclasses_are_frozen_and_typed() -> None:
    event = DiscDropped(seat=0, column=3)

    assert event.seat == 0
    assert event.column == 3
    assert event.event_type == "DiscDropped"

    with pytest.raises(FrozenInstanceError):
        event.column = 4  # type: ignore[misc]


def test_domain_event_values_are_comparable() -> None:
    assert DiscDropped(seat=0, column=3) == DiscDropped(seat=0, column=3)
    assert DiscDropped(seat=0, column=3) != DiscDropped(seat=1, column=3)
