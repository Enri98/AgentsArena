"""Tests for seat validation helpers."""

from __future__ import annotations

import pytest

from arena.core.seats import is_seat


@pytest.mark.parametrize("value", [0, 1, 7, 10_000])
def test_is_seat_accepts_non_negative_integers(value: object) -> None:
    assert is_seat(value) is True


@pytest.mark.parametrize("value", [-1, -5, True, False, 1.0, "1", None])
def test_is_seat_rejects_invalid_inputs_without_coercion(value: object) -> None:
    assert is_seat(value) is False
