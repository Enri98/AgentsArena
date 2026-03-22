"""Shared rule-result abstractions for the simulation core."""

from __future__ import annotations

from dataclasses import dataclass

from arena.core.types import Seat


@dataclass(frozen=True)
class RuleResult:
    """Base class for pure, game-agnostic rule outcomes."""

    @property
    def result_type(self) -> str:
        """Return a stable result type identifier for the concrete outcome."""

        return self.__class__.__name__


@dataclass(frozen=True)
class Win(RuleResult):
    """A generic winning outcome for a single seat."""

    seat: Seat


@dataclass(frozen=True)
class Draw(RuleResult):
    """A generic drawn outcome."""


__all__ = ["RuleResult", "Win", "Draw"]
