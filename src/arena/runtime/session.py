"""Pure in-memory runtime coordinator for local match sessions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Generic, TypeVar

from arena.adapters.in_process import (
    PayloadPolicy,
    apply_payload_policy_joint_turn,
    apply_payload_policy_turn,
)
from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.exceptions import ArenaCoreError
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import RuleResult
from arena.core.simultaneous import acting_seats, is_joint_node
from arena.core.types import Seat
from arena.match.local_match import LocalMatch, start_match
from arena.runtime.exceptions import RuntimeStateError
from arena.runtime.ids import MatchId, generate_match_id
from arena.runtime.models import (
    AbortMetadata,
    AbortReason,
    MatchAborted,
    MatchCreated,
    MatchFinished,
    MatchStarted,
    PlayerRecord,
    RuntimeEvent,
    RuntimeLifecycle,
    TurnAccepted,
    TurnRequested,
)

ConfigT = TypeVar("ConfigT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
ResultT = TypeVar("ResultT", bound=RuleResult)


@dataclass(frozen=True)
class MatchSession(Generic[ConfigT, StateT, ActionT, ObservationT, ResultT]):
    """Runtime-owned wrapper around one local match execution."""

    match_id: MatchId
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT]
    config: ConfigT
    players: tuple[PlayerRecord, ...]
    policy_bindings: Mapping[Seat, PayloadPolicy]
    lifecycle: RuntimeLifecycle
    local_match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT] | None
    events: tuple[RuntimeEvent, ...]
    abort: AbortMetadata | None = None


@dataclass(frozen=True)
class Arena:
    """Small pure coordinator for local runtime sessions."""

    id_factory: Callable[[], MatchId] = generate_match_id

    def create_session(
        self,
        definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
        config: ConfigT,
        players: Sequence[PlayerRecord],
        policy_bindings: Mapping[Seat, PayloadPolicy],
        *,
        match_id: str | MatchId | None = None,
    ) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
        """Create a local runtime session without starting the game rules yet."""

        resolved_match_id = _resolve_match_id(match_id, self.id_factory)
        player_tuple = tuple(players)
        _ensure_unique_player_seats(player_tuple)
        _ensure_unique_player_ids(player_tuple)

        return MatchSession(
            match_id=resolved_match_id,
            definition=definition,
            config=config,
            players=player_tuple,
            policy_bindings=MappingProxyType(dict(policy_bindings)),
            lifecycle=RuntimeLifecycle.CREATED,
            local_match=None,
            events=(MatchCreated(match_id=resolved_match_id, players=player_tuple),),
        )

    def start_session(
        self,
        session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
        *,
        seed: int | None = None,
    ) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
        """Start the local match owned by a created runtime session.

        ``seed`` fixes the rolls of a game with chance nodes; when omitted the
        match mints a secret one. It is held by the local match and never
        appears in any runtime payload.
        """

        if session.lifecycle is not RuntimeLifecycle.CREATED:
            raise RuntimeStateError(
                "Only created sessions can be started.",
                details={"match_id": session.match_id, "lifecycle": session.lifecycle.value},
            )

        try:
            local_match = start_match(session.definition, session.config, seed=seed)
        except ArenaCoreError as error:
            return _abort_session(
                session,
                reason=AbortReason.CORE_ERROR,
                message="The runtime session failed while creating the local match.",
                cause=error,
            )
        except Exception as error:
            return _abort_session(
                session,
                reason=AbortReason.RUNTIME_ERROR,
                message="The runtime session failed unexpectedly while starting.",
                cause=error,
            )

        lifecycle = (
            RuntimeLifecycle.FINISHED
            if local_match.rules_engine.is_terminal(local_match.state)
            else RuntimeLifecycle.RUNNING
        )
        events: tuple[RuntimeEvent, ...] = session.events + (
            MatchStarted(match_id=session.match_id),
        )
        if lifecycle is RuntimeLifecycle.FINISHED:
            events = events + (MatchFinished(match_id=session.match_id),)

        return replace(
            session,
            lifecycle=lifecycle,
            local_match=local_match,
            events=events,
        )

    def request_turn(
        self,
        session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    ) -> tuple[MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT], Seat]:
        """Append TurnRequested to the session and return the session plus active seat.

        Raises RuntimeStateError when the session is not running or has no match.
        """

        if session.lifecycle is not RuntimeLifecycle.RUNNING:
            raise RuntimeStateError(
                "Only running sessions can be advanced.",
                details={"match_id": session.match_id, "lifecycle": session.lifecycle.value},
            )
        if session.local_match is None:
            raise RuntimeStateError("Running session has no local match.")

        local_match = session.local_match
        if is_joint_node(local_match.rules_engine, local_match.state):
            # Several seats act at once: step_session resolves the round.
            raise RuntimeStateError(
                "Several seats act at once here; advance with step_session.",
                details={"match_id": session.match_id},
            )
        seats = acting_seats(local_match.rules_engine, local_match.state)
        seat = seats[0] if seats else local_match.rules_engine.current_seat(local_match.state)
        requested_session = replace(
            session,
            events=session.events + (TurnRequested(match_id=session.match_id, seat=seat),),
        )
        return requested_session, seat

    def complete_turn(
        self,
        requested_session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
        seat: Seat,
    ) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
        """Call the policy for *seat* and return the resulting session."""

        local_match = requested_session.local_match
        assert local_match is not None

        if seat not in requested_session.policy_bindings:
            return _abort_session(
                requested_session,
                reason=AbortReason.MISSING_POLICY,
                message=f"No policy is bound for active seat {seat}.",
                cause=None,
            )

        try:
            next_match = apply_payload_policy_turn(
                local_match,
                requested_session.policy_bindings[seat],
            )
        except ArenaCoreError as error:
            return _abort_session(
                requested_session,
                reason=AbortReason.CORE_ERROR,
                message="The active policy returned an action rejected by the rules engine.",
                cause=error,
            )
        except Exception as error:
            return _abort_session(
                requested_session,
                reason=AbortReason.ADAPTER_ERROR,
                message="The active policy failed to produce a valid action response.",
                cause=error,
            )

        accepted_session = replace(
            requested_session,
            local_match=next_match,
            events=requested_session.events
            + (
                TurnAccepted(
                    match_id=requested_session.match_id,
                    seat=seat,
                    # The accepted action's own turn, 1-based. Not the new turn
                    # count: chance turns may follow it in the same step.
                    turn_index=len(local_match.turns) + 1,
                ),
            ),
        )
        if next_match.rules_engine.is_terminal(next_match.state):
            return _finish_session(accepted_session)
        return accepted_session

    def step_session(
        self,
        session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    ) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
        """Advance one local runtime turn by delegating to the active seat policy."""

        if session.lifecycle is not RuntimeLifecycle.RUNNING:
            raise RuntimeStateError(
                "Only running sessions can be advanced.",
                details={"match_id": session.match_id, "lifecycle": session.lifecycle.value},
            )
        if session.local_match is None:
            raise RuntimeStateError("Running session has no local match.")

        local_match = session.local_match
        if local_match.rules_engine.is_terminal(local_match.state):
            return _finish_session(session)

        if is_joint_node(local_match.rules_engine, local_match.state):
            return self._step_joint(session)
        requested_session, seat = self.request_turn(session)
        return self.complete_turn(requested_session, seat)

    def _step_joint(
        self,
        session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    ) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
        """Resolve a joint node (Phase 41): every acting seat's policy decides.

        One ``TurnRequested`` and, once the round is applied, one
        ``TurnAccepted`` per acting seat, all naming the round's turn.
        """

        local_match = session.local_match
        assert local_match is not None
        seats = acting_seats(local_match.rules_engine, local_match.state)
        requested = replace(
            session,
            events=session.events
            + tuple(TurnRequested(match_id=session.match_id, seat=seat) for seat in seats),
        )
        missing = [seat for seat in seats if seat not in requested.policy_bindings]
        if missing:
            return _abort_session(
                requested,
                reason=AbortReason.MISSING_POLICY,
                message=f"No policy is bound for acting seat {missing[0]}.",
                cause=None,
            )
        try:
            next_match = apply_payload_policy_joint_turn(
                local_match,
                {seat: requested.policy_bindings[seat] for seat in seats},
            )
        except ArenaCoreError as error:
            return _abort_session(
                requested,
                reason=AbortReason.CORE_ERROR,
                message="An acting policy returned an action rejected by the rules engine.",
                cause=error,
            )
        except Exception as error:
            return _abort_session(
                requested,
                reason=AbortReason.ADAPTER_ERROR,
                message="An acting policy failed to produce a valid action response.",
                cause=error,
            )
        turn_index = len(local_match.turns) + 1
        accepted = replace(
            requested,
            local_match=next_match,
            events=requested.events
            + tuple(
                TurnAccepted(match_id=session.match_id, seat=seat, turn_index=turn_index)
                for seat in seats
            ),
        )
        if next_match.rules_engine.is_terminal(next_match.state):
            return _finish_session(accepted)
        return accepted

    def run_session(
        self,
        session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    ) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
        """Start if needed, then run until the session finishes or aborts."""

        current = session
        if current.lifecycle is RuntimeLifecycle.CREATED:
            current = self.start_session(current)

        while current.lifecycle is RuntimeLifecycle.RUNNING:
            current = self.step_session(current)

        return current

    def abort_session(
        self,
        session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
        *,
        reason: AbortReason = AbortReason.CANCELLED,
        message: str = "The runtime session was cancelled.",
    ) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
        """Abort a runtime session without assigning a game result."""

        if session.lifecycle in (RuntimeLifecycle.FINISHED, RuntimeLifecycle.ABORTED):
            raise RuntimeStateError(
                "Finished or aborted sessions cannot be aborted again.",
                details={"match_id": session.match_id, "lifecycle": session.lifecycle.value},
            )
        return _abort_session(session, reason=reason, message=message, cause=None)


def _resolve_match_id(
    match_id: str | MatchId | None,
    id_factory: Callable[[], MatchId],
) -> MatchId:
    if match_id is None:
        return id_factory()
    return match_id if isinstance(match_id, MatchId) else MatchId(match_id)


def _ensure_unique_player_seats(players: Sequence[PlayerRecord]) -> None:
    seats = [player.seat for player in players]
    if len(seats) != len(set(seats)):
        raise RuntimeStateError("Player seat assignments must be unique.")


def _ensure_unique_player_ids(players: Sequence[PlayerRecord]) -> None:
    player_ids = [player.player_id for player in players]
    if len(player_ids) != len(set(player_ids)):
        raise RuntimeStateError("Player ids must be unique.")


def _finish_session(
    session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    return replace(
        session,
        lifecycle=RuntimeLifecycle.FINISHED,
        events=session.events + (MatchFinished(match_id=session.match_id),),
    )


def _abort_session(
    session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    *,
    reason: AbortReason,
    message: str,
    cause: BaseException | None,
) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    abort = AbortMetadata.from_cause(reason=reason, message=message, cause=cause)
    return replace(
        session,
        lifecycle=RuntimeLifecycle.ABORTED,
        abort=abort,
        events=session.events + (MatchAborted(match_id=session.match_id, abort=abort),),
    )


def record_runtime_event(
    session: MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT],
    event: RuntimeEvent,
) -> MatchSession[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Append a runtime event to a session without changing lifecycle."""

    return replace(session, events=session.events + (event,))


__all__: Sequence[str] = [
    "Arena",
    "MatchSession",
    "record_runtime_event",
]
