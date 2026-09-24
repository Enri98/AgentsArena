"""Shared domain event abstractions for the simulation core."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arena.core.types import Seat

#: Seats an event's audience is computed over. Two-seat today; the one place to
#: widen when N-player lands.
EVENT_AUDIENCE_SEATS: tuple[Seat, ...] = (0, 1)


@dataclass(frozen=True)
class DomainEvent:
    """Base class for pure simulation-domain events.

    Events are public by default. An event carrying private information (Phase
    38) — one seat's dealt hand, say — overrides :meth:`visible_to`. The server
    delivers an event only to viewers it is visible to, and records its audience
    in the transcript so a redacted copy can be produced later.
    """

    @property
    def event_type(self) -> str:
        """Return a stable event type identifier for the concrete event."""

        return self.__class__.__name__

    def visible_to(self, viewer: Seat | None) -> bool:
        """Whether ``viewer`` may see this event; ``None`` means the public."""

        return True

    @property
    def is_public(self) -> bool:
        return self.visible_to(None)

    def audience(self) -> list[Seat] | None:
        """Seats entitled to a non-public event; ``None`` for a public one."""

        if self.is_public:
            return None
        return [seat for seat in EVENT_AUDIENCE_SEATS if self.visible_to(seat)]


def event_payload_visible_to(payload: dict, viewer: Seat | None) -> bool:
    """Visibility of a *serialized* event (``is_public`` / ``audience`` keys).

    Payloads written before Phase 38 carry neither key and are public.
    """

    if payload.get("is_public", True):
        return True
    if viewer is None:
        return False
    return viewer in (payload.get("audience") or ())


__all__: Sequence[str] = ["DomainEvent", "EVENT_AUDIENCE_SEATS", "event_payload_visible_to"]
