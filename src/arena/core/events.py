"""Shared domain event abstractions for the simulation core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainEvent:
    """Base class for pure simulation-domain events."""

    @property
    def event_type(self) -> str:
        """Return a stable event type identifier for the concrete event."""

        return self.__class__.__name__


__all__ = ["DomainEvent"]
