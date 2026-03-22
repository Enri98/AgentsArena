"""Tests for shared core type aliases."""

from arena.core.types import Seat


def test_seat_alias_is_the_canonical_int_alias() -> None:
    assert Seat is int
