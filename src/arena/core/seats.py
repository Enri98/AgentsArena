"""Seat-related helpers for the simulation core."""

from __future__ import annotations

from typing import TypeGuard

from arena.core.types import Seat


def is_seat(value: object) -> TypeGuard[Seat]:
    """Return whether a value is a valid simulation seat identifier."""

    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


__all__ = ["is_seat"]
