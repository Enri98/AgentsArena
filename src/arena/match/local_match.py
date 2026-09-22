"""Pure local match/session execution for simulation games."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Generic, TypeVar, cast

from arena.core.actions import Action
from arena.core.chance import is_chance_node, resolve_chance
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
from arena.core.exceptions import ChanceResolutionError
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import RuleResult
from arena.core.rules_engine import RulesEngine
from arena.core.serializer import SnapshotEnvelope
from arena.core.types import Seat

ConfigT = TypeVar("ConfigT", bound=BaseGameConfig)
StateT = TypeVar("StateT")
ActionT = TypeVar("ActionT", bound=Action)
ObservationT = TypeVar("ObservationT", bound=Observation)
ResultT = TypeVar("ResultT", bound=RuleResult)

SNAPSHOT_SCHEMA_VERSION = 1

#: A turn produced by a seat acting.
TURN_KIND_ACTION = "action"
#: A turn produced by the rules engine resolving a chance node (Phase 37).
TURN_KIND_CHANCE = "chance"

#: Guard against an engine whose chance node never settles. A legitimate game
#: resolves a handful at most; anything beyond this is a bug in the engine, and
#: hanging the match loop would be a worse way to discover it.
MAX_CONSECUTIVE_CHANCE_STEPS = 128


@dataclass(frozen=True)
class TurnRecord(Generic[StateT, ActionT, ResultT]):
    """Immutable record of one local-match turn.

    A turn is either a seat acting (``kind="action"``) or the rules engine
    resolving a chance node (``kind="chance"``, Phase 37). A chance turn carries
    no seat and no action — nobody chose it — but is otherwise an ordinary step:
    it has events describing the outcome, a post-state, and a snapshot, and it
    occupies its own position in the transcript.
    """

    seat: Seat | None
    action: ActionT | None
    events: tuple[DomainEvent, ...]
    result: ResultT | None
    post_state: StateT
    post_snapshot: SnapshotEnvelope
    kind: str = TURN_KIND_ACTION


@dataclass(frozen=True)
class LocalMatch(Generic[ConfigT, StateT, ActionT, ObservationT, ResultT]):
    """Immutable local match state for a registered game definition."""

    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT]
    rules_engine: RulesEngine[ConfigT, StateT, ActionT, ObservationT]
    config: ConfigT
    state: StateT
    initial_snapshot: SnapshotEnvelope
    turns: tuple[TurnRecord[StateT, ActionT, ResultT], ...]


def start_match(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    config: ConfigT,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Start a new immutable local match from a definition and config."""

    rules_engine = deepcopy(definition.rules_engine)
    state = rules_engine.initial_state(config)
    initial_snapshot = _build_snapshot(definition, config, state)

    # A game may open at a chance node — a deal or an opening roll. Resolving it
    # here means a started match is never left waiting on nobody.
    state, turns = _drain_chance_nodes(definition, rules_engine, config, state, ())

    return LocalMatch(
        definition=definition,
        rules_engine=rules_engine,
        config=config,
        state=state,
        initial_snapshot=initial_snapshot,
        turns=turns,
    )


def apply_match_action(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    seat: Seat,
    action: ActionT,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Apply one action to a local match and return a new immutable match state."""

    transition = match.rules_engine.apply_action(match.state, seat, action)
    post_snapshot = _build_snapshot(match.definition, match.config, transition.state)
    turn_record = TurnRecord(
        seat=seat,
        action=action,
        events=transition.events,
        result=cast(ResultT | None, transition.result),
        post_state=transition.state,
        post_snapshot=post_snapshot,
    )

    state, turns = _drain_chance_nodes(
        match.definition,
        match.rules_engine,
        match.config,
        transition.state,
        match.turns + (turn_record,),
    )

    return replace(match, state=state, turns=turns)


def _drain_chance_nodes(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    rules_engine: RulesEngine[ConfigT, StateT, ActionT, ObservationT],
    config: ConfigT,
    state: StateT,
    turns: tuple[TurnRecord[StateT, ActionT, ResultT], ...],
) -> tuple[StateT, tuple[TurnRecord[StateT, ActionT, ResultT], ...]]:
    """Resolve chance nodes until a seat is to move, recording each as a turn.

    Chance is drained as part of stepping rather than surfaced to callers, so a
    settled match never rests at a node where nobody is to move. That is what
    lets ``RulesEngine.current_seat`` keep its contract: every observer of a
    settled match sees a seat.
    """

    steps = 0
    while is_chance_node(rules_engine, state):
        steps += 1
        if steps > MAX_CONSECUTIVE_CHANCE_STEPS:
            raise ChanceResolutionError(
                f"Game '{definition.game_id}' is still at a chance node after "
                f"{MAX_CONSECUTIVE_CHANCE_STEPS} consecutive resolutions; its "
                f"resolve_chance is not making progress.",
                details={"game_id": definition.game_id, "steps": steps},
            )

        transition = resolve_chance(rules_engine, state)
        state = transition.state
        turns = turns + (
            TurnRecord(
                seat=None,
                action=None,
                events=transition.events,
                result=cast(ResultT | None, transition.result),
                post_state=state,
                post_snapshot=_build_snapshot(definition, config, state),
                kind=TURN_KIND_CHANCE,
            ),
        )

    return state, turns


def _build_snapshot(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    config: ConfigT,
    state: StateT,
) -> SnapshotEnvelope:
    return SnapshotEnvelope(
        game_id=definition.game_id,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        config=definition.serializer.dump_config(config),
        state=definition.serializer.dump_state(state),
    )


__all__: Sequence[str] = [
    "LocalMatch",
    "SNAPSHOT_SCHEMA_VERSION",
    "TurnRecord",
    "apply_match_action",
    "start_match",
]
