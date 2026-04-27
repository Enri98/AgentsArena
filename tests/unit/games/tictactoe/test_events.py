"""Tests for Tic-Tac-Toe domain events."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from arena.core.events import DomainEvent
from arena.core.results import Draw, Win
from arena.games.tictactoe import GameDrawn, MarkPlaced, WinnerDetected
from arena.games.tictactoe import __all__ as tictactoe_exports


def test_tictactoe_events_are_importable_and_typed() -> None:
    placed = MarkPlaced(seat=0, row=1, column=2)
    winner = WinnerDetected(winning_seat=1)
    drawn = GameDrawn()

    assert isinstance(placed, DomainEvent)
    assert isinstance(winner, DomainEvent)
    assert isinstance(drawn, DomainEvent)
    assert placed.event_type == "MarkPlaced"
    assert winner.event_type == "WinnerDetected"
    assert drawn.event_type == "GameDrawn"


def test_tictactoe_package_exports_the_event_surface() -> None:
    assert "MarkPlaced" in tictactoe_exports
    assert "WinnerDetected" in tictactoe_exports
    assert "GameDrawn" in tictactoe_exports


def test_tictactoe_events_are_frozen_value_objects() -> None:
    event = MarkPlaced(seat=0, row=2, column=1)

    with pytest.raises(FrozenInstanceError):
        event.row = 0  # type: ignore[misc]


def test_tictactoe_events_have_value_semantics() -> None:
    assert MarkPlaced(seat=0, row=1, column=2) == MarkPlaced(seat=0, row=1, column=2)
    assert WinnerDetected(winning_seat=0) != WinnerDetected(winning_seat=1)
    assert GameDrawn() == GameDrawn()


def test_tictactoe_reuses_the_shared_result_surface() -> None:
    assert Win(seat=0).result_type == "Win"
    assert Draw().result_type == "Draw"
