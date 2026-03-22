"""Shared observation abstractions for the simulation core."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.types import Seat


@dataclass(frozen=True)
class Observation:
    """Base class for player-facing state views."""

    seat: Seat

    @property
    def observation_type(self) -> str:
        """Return a stable observation type identifier for the concrete observation."""

        return self.__class__.__name__


__all__ = ["Observation"]
