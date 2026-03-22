"""Shared action abstractions for the simulation core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """Base class for pure, seat-agnostic game actions."""

    @property
    def action_type(self) -> str:
        """Return a stable action type identifier for the concrete action."""

        return self.__class__.__name__


__all__ = ["Action"]
