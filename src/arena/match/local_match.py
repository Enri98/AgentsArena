"""Pure local match/session execution for simulation games."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Generic, TypeVar, cast

from arena.core.actions import Action
from arena.core.chance import ChanceRng, apply_chance, is_chance_node, sample_chance
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
#: A turn produced by resolving a chance node (Phase 37).
TURN_KIND_CHANCE = "chance"

#: Guard against an engine whose chance node never settles. A legitimate game
#: resolves a handful at most; anything beyond this is a bug in the engine, and
#: hanging the match loop would be a worse way to discover it.
MAX_CONSECUTIVE_CHANCE_STEPS = 128

#: Bits of entropy in a minted chance seed, matching the match-id token.
CHANCE_SEED_BITS = 128


@dataclass(frozen=True)
class TurnRecord(Generic[StateT, ActionT, ResultT]):
    """Immutable record of one local-match turn.

    A turn is either a seat acting (``kind="action"``) or a chance node being
    resolved (``kind="chance"``, Phase 37). A chance turn carries no seat and no
    action — nobody chose it. It carries the ``outcome`` instead, which is what
    replay applies; otherwise it is an ordinary step with events, a post-state,
    and a snapshot, occupying its own position in the transcript.
    """

    seat: Seat | None
    action: ActionT | None
    events: tuple[DomainEvent, ...]
    result: ResultT | None
    post_state: StateT
    post_snapshot: SnapshotEnvelope
    kind: str = TURN_KIND_ACTION
    outcome: Any = None


@dataclass(frozen=True)
class LocalMatch(Generic[ConfigT, StateT, ActionT, ObservationT, ResultT]):
    """Immutable local match state for a registered game definition.

    ``rng`` is the match's private chance generator (Phase 37). It is ``None`` for
    a deterministic game, and for a replay, which applies recorded outcomes and
    never samples. It is deliberately not part of ``state``, ``config``, or any
    snapshot — all of which are broadcast — and it is hidden from ``repr``.
    """

    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT]
    rules_engine: RulesEngine[ConfigT, StateT, ActionT, ObservationT]
    config: ConfigT
    state: StateT
    initial_snapshot: SnapshotEnvelope
    turns: tuple[TurnRecord[StateT, ActionT, ResultT], ...]
    rng: ChanceRng | None = field(default=None, repr=False, compare=False)


def start_match(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    config: ConfigT,
    *,
    seed: int | None = None,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Start a new immutable local match from a definition and config.

    For a game with chance nodes, ``seed`` fixes every roll: the same seed and
    the same actions reproduce the same match. When omitted, a fresh seed is
    minted from ``secrets`` — a predictable default would let anyone who knows
    it predict the dice. A deterministic game ignores the seed.
    """

    rng: ChanceRng | None = None
    if definition.has_chance_nodes:
        rng = ChanceRng(
            seed=seed if seed is not None else secrets.randbits(CHANCE_SEED_BITS)
        )
    return _start(definition, config, rng)


def start_replay_match(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    config: ConfigT,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Start a match that never samples chance, for replaying a transcript.

    It stops at each chance node and waits for :func:`apply_match_chance` to
    supply the recorded outcome. That is what makes replay independent of the
    seed: a transcript validates without it.
    """

    return _start(definition, config, None)


def _start(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    config: ConfigT,
    rng: ChanceRng | None,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    rules_engine = deepcopy(definition.rules_engine)
    state = rules_engine.initial_state(config)
    initial_snapshot = _build_snapshot(definition, config, state)

    # A game may open at a chance node — a deal or an opening roll. Resolving it
    # here means a started live match is never left waiting on nobody.
    state, turns, rng = _drain_chance_nodes(definition, rules_engine, config, state, (), rng)

    return LocalMatch(
        definition=definition,
        rules_engine=rules_engine,
        config=config,
        state=state,
        initial_snapshot=initial_snapshot,
        turns=turns,
        rng=rng,
    )


def apply_match_action(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    seat: Seat,
    action: ActionT,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Apply one action to a local match and return a new immutable match state."""

    if is_chance_node(match.rules_engine, match.state):
        raise ChanceResolutionError(
            "The match is awaiting a chance outcome, so no seat can act.",
            details={"game_id": match.definition.game_id, "seat": seat},
        )

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

    state, turns, rng = _drain_chance_nodes(
        match.definition,
        match.rules_engine,
        match.config,
        transition.state,
        match.turns + (turn_record,),
        match.rng,
    )

    return replace(match, state=state, turns=turns, rng=rng)


def apply_match_chance(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    outcome: object,
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Apply a recorded chance outcome to a match waiting at a chance node.

    Only a replay match (see :func:`start_replay_match`) ever waits at one; a
    live match drains its own. The engine revalidates the outcome.
    """

    if not is_chance_node(match.rules_engine, match.state):
        raise ChanceResolutionError(
            "No chance node is pending, so a chance outcome cannot be applied.",
            details={"game_id": match.definition.game_id},
        )

    state, turn = _resolve_one(
        match.definition, match.rules_engine, match.config, match.state, outcome
    )
    state, turns, rng = _drain_chance_nodes(
        match.definition,
        match.rules_engine,
        match.config,
        state,
        match.turns + (turn,),
        match.rng,
    )
    return replace(match, state=state, turns=turns, rng=rng)


def _resolve_one(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    rules_engine: RulesEngine[ConfigT, StateT, ActionT, ObservationT],
    config: ConfigT,
    state: StateT,
    outcome: object,
) -> tuple[StateT, TurnRecord[StateT, ActionT, ResultT]]:
    transition = apply_chance(rules_engine, state, outcome)
    post_state = cast(StateT, transition.state)
    return post_state, TurnRecord(
        seat=None,
        action=None,
        events=transition.events,
        result=cast(ResultT | None, transition.result),
        post_state=post_state,
        post_snapshot=_build_snapshot(definition, config, post_state),
        kind=TURN_KIND_CHANCE,
        outcome=outcome,
    )


def _drain_chance_nodes(
    definition: GameDefinition[ConfigT, StateT, ActionT, ObservationT, ResultT],
    rules_engine: RulesEngine[ConfigT, StateT, ActionT, ObservationT],
    config: ConfigT,
    state: StateT,
    turns: tuple[TurnRecord[StateT, ActionT, ResultT], ...],
    rng: ChanceRng | None,
) -> tuple[StateT, tuple[TurnRecord[StateT, ActionT, ResultT], ...], ChanceRng | None]:
    """Sample chance nodes until a seat is to move, recording each as a turn.

    Chance is drained as part of stepping rather than surfaced to callers, so a
    settled live match never rests at a node where nobody is to move. That is
    what lets ``RulesEngine.current_seat`` keep its contract.

    With no generator — a replay — nothing is sampled: the match stops at the
    chance node and waits for the recorded outcome.
    """

    if rng is None:
        return state, turns, rng

    steps = 0
    while is_chance_node(rules_engine, state):
        steps += 1
        if steps > MAX_CONSECUTIVE_CHANCE_STEPS:
            raise ChanceResolutionError(
                f"Game '{definition.game_id}' is still at a chance node after "
                f"{MAX_CONSECUTIVE_CHANCE_STEPS} consecutive resolutions; its "
                f"apply_chance is not making progress.",
                details={"game_id": definition.game_id, "steps": steps},
            )

        outcome, rng = sample_chance(rules_engine, state, rng)
        state, turn = _resolve_one(definition, rules_engine, config, state, outcome)
        turns = turns + (turn,)

    return state, turns, rng


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
    "apply_match_chance",
    "start_match",
    "start_replay_match",
]
