"""Pure local match/session execution for simulation games."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Generic, TypeVar, cast

from arena.core.actions import Action
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
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


@dataclass(frozen=True)
class TurnRecord(Generic[StateT, ActionT, ResultT]):
    """Immutable record of one accepted local-match turn."""

    seat: Seat
    action: ActionT
    events: tuple[DomainEvent, ...]
    result: ResultT | None
    post_state: StateT
    post_snapshot: SnapshotEnvelope


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

    return LocalMatch(
        definition=definition,
        rules_engine=rules_engine,
        config=config,
        state=state,
        initial_snapshot=initial_snapshot,
        turns=(),
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

    return replace(
        match,
        state=transition.state,
        turns=match.turns + (turn_record,),
    )


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
