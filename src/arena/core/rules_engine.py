"""Shared rules-engine contracts and transition types."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar, runtime_checkable

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
from arena.core.observations import Observation
from arena.core.results import RuleResult
from arena.core.types import Seat

ConfigT = TypeVar("ConfigT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
EventT = TypeVar("EventT", bound=DomainEvent)
ResultT = TypeVar("ResultT", bound=RuleResult | None)


@dataclass(frozen=True)
class TransitionResult(Generic[StateT, EventT, ResultT]):
    """Pure post-transition payload returned by a rules engine."""

    state: StateT
    events: tuple[EventT, ...] = field(default_factory=tuple)
    result: ResultT = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))


@runtime_checkable
class RulesEngine(Protocol[ConfigT, StateT, ActionT, ObservationT]):
    """Shared contract that concrete game rules engines must satisfy."""

    def initial_state(self, config: ConfigT) -> StateT:
        """Create the validated initial state for a game config."""

    def current_seat(self, state: StateT) -> Seat:
        """Return the seat whose turn it is in the given state."""

    def legal_actions(self, state: StateT, seat: Seat) -> tuple[ActionT, ...]:
        """Return the legal actions available to a seat in the given state."""

    def validate_action(self, state: StateT, seat: Seat, action: ActionT) -> None:
        """Raise a domain exception if the action is not legal."""

    def apply_action(
        self,
        state: StateT,
        seat: Seat,
        action: ActionT,
    ) -> TransitionResult[StateT, DomainEvent, RuleResult | None]:
        """Apply an action defensively and return the pure transition payload."""

    def is_terminal(self, state: StateT) -> bool:
        """Return whether the given state is terminal."""

    def result(self, state: StateT) -> RuleResult | None:
        """Return the terminal result for a state, if any."""

    def observation(self, state: StateT, seat: Seat) -> ObservationT:
        """Build a player-facing observation for the given seat."""


__all__: Sequence[str] = ["RulesEngine", "TransitionResult"]
