"""Tests for Connect 4 domain events."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arena.core.events import DomainEvent
from arena.core.results import Draw, Win
from arena.games.connect4 import DiscDropped, GameDrawn, WinnerDetected
from arena.games.connect4 import __all__ as connect4_exports


def test_connect4_events_are_importable_and_typed() -> None:
    dropped = DiscDropped(seat=0, column=3, row=5)
    winner = WinnerDetected(winning_seat=1)
    drawn = GameDrawn()

    assert isinstance(dropped, DomainEvent)
    assert isinstance(winner, DomainEvent)
    assert isinstance(drawn, DomainEvent)
    assert dropped.event_type == "DiscDropped"
    assert winner.event_type == "WinnerDetected"
    assert drawn.event_type == "GameDrawn"


def test_connect4_package_exports_the_phase5_event_surface() -> None:
    assert "DiscDropped" in connect4_exports
    assert "WinnerDetected" in connect4_exports
    assert "GameDrawn" in connect4_exports


def test_connect4_events_are_frozen_value_objects() -> None:
    event = DiscDropped(seat=0, column=2, row=4)

    with pytest.raises(FrozenInstanceError):
        event.row = 3  # type: ignore[misc]


def test_connect4_events_have_value_semantics() -> None:
    assert DiscDropped(seat=0, column=1, row=5) == DiscDropped(seat=0, column=1, row=5)
    assert WinnerDetected(winning_seat=0) != WinnerDetected(winning_seat=1)
    assert GameDrawn() == GameDrawn()


def test_connect4_reuses_the_shared_result_surface() -> None:
    assert Win(seat=0).result_type == "Win"
    assert Draw().result_type == "Draw"
