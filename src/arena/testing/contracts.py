"""Reusable contract assertions for game implementations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from arena.core.chance import is_chance_node
from arena.core.exceptions import ArenaCoreError
from arena.core.public_view import (
    dump_config_for_seat,
    dump_public_config,
    dump_public_state,
    dump_state_for_seat,
    load_public_state,
    public_state,
)
from arena.core.seats import is_seat
from arena.core.serializer import Serializer
from arena.core.simultaneous import acting_seats, apply_joint_action


@runtime_checkable
class GameContractBundle(Protocol):
    """Fixture bundle contract used by the shared game-contract assertions.

    A hidden-information game's bundle must also define ``private_variants``
    (a sequence of :class:`PrivateVariant`, covering every seat as the blind one)
    and, if it has chance nodes, ``chance_state`` plus ``private_outcome_variants``.
    See :func:`assert_seat_view_contract`.

    A game that opens at a chance node must define ``opening_outcomes``: the
    outcomes that take ``initial_state(config)`` to ``bundle.initial_state``.

    A hidden-information game with an action that legitimately reveals private
    information to the table (a showdown) lists it in ``revealing_actions``.

    A bundle may also define ``terminal_action``: the action that takes
    ``near_terminal_state`` to ``terminal_state``, when that is not
    ``legal_action``. Pig needs it — only ``roll`` is legal as a turn opens, and
    only ``hold`` can end the game. It is optional so existing bundles are
    unaffected.
    """

    definition: object
    config: object
    initial_state: object
    near_terminal_state: object
    terminal_state: object
    legal_action: object
    illegal_action: object


def assert_valid_initial_state(bundle: GameContractBundle) -> None:
    """Assert that a game exposes a coherent validated initial state."""

    rules_engine = bundle.definition.rules_engine
    initial_state = rules_engine.initial_state(bundle.config)

    if is_chance_node(rules_engine, initial_state):
        # A game that opens at a chance node (a deal, an opening roll) has no seat
        # to move until the opening resolves. The bundle names the outcomes, and the
        # engine must reach bundle.initial_state from its own initial state by
        # applying them: a settled state the bundle merely asserts proves nothing.
        outcomes = getattr(bundle, "opening_outcomes", None)
        assert outcomes, (
            "initial state contract failed: a game that opens at a chance node must "
            "supply bundle.opening_outcomes"
        )
        for outcome in outcomes:
            assert is_chance_node(rules_engine, initial_state), (
                "initial state contract failed: more opening_outcomes than chance nodes"
            )
            initial_state = rules_engine.apply_chance(initial_state, outcome).state
        assert not is_chance_node(rules_engine, initial_state), (
            "initial state contract failed: opening_outcomes do not settle the opening"
        )
    assert initial_state == bundle.initial_state, (
        "initial state contract failed: rules engine did not reproduce the bundle's "
        "initial_state from the provided config"
    )

    seat = rules_engine.current_seat(initial_state)
    assert is_seat(seat), "initial state contract failed: current_seat must return a valid seat id"
    assert not rules_engine.is_terminal(initial_state), (
        "initial state contract failed: initial_state must not be terminal"
    )
    assert rules_engine.result(initial_state) is None, (
        "initial state contract failed: initial_state must not report a terminal result"
    )


def _apply(rules_engine: object, state: object, action: object) -> object:
    """Apply ``action`` as the acting seat would: at a joint node (Phase 41) every
    acting seat plays it, so a simultaneous game runs the same contract."""

    seats = acting_seats(rules_engine, state)
    if len(seats) > 1:
        return apply_joint_action(rules_engine, state, {seat: action for seat in seats})
    seat = seats[0] if seats else rules_engine.current_seat(state)  # type: ignore[attr-defined]
    return rules_engine.apply_action(state, seat, action)  # type: ignore[attr-defined]


def assert_legal_action_generation(bundle: GameContractBundle) -> None:
    """Assert that ongoing states expose valid legal actions."""

    rules_engine = bundle.definition.rules_engine
    state = bundle.initial_state
    seat = rules_engine.current_seat(state)
    legal_actions = rules_engine.legal_actions(state, seat)
    action_type = bundle.definition.action_type

    assert legal_actions, (
        "legal action generation contract failed: ongoing states must expose "
        "at least one legal action"
    )
    assert bundle.legal_action in legal_actions, (
        "legal action generation contract failed: bundle.legal_action must be "
        "present in legal_actions"
    )

    for action in legal_actions:
        assert isinstance(action, action_type), (
            "legal action generation contract failed: legal actions must match the game "
            "definition's declared action_type"
        )
        try:
            rules_engine.validate_action(state, seat, action)
        except ArenaCoreError as exc:  # pragma: no cover - exercised by negative tests
            raise AssertionError(
                "legal action generation contract failed: legal actions must validate successfully"
            ) from exc


def assert_illegal_action_rejection(bundle: GameContractBundle) -> None:
    """Assert that intentionally illegal actions fail predictably."""

    rules_engine = bundle.definition.rules_engine
    state = bundle.initial_state
    seat = rules_engine.current_seat(state)

    try:
        rules_engine.validate_action(state, seat, bundle.illegal_action)
    except ArenaCoreError:
        pass
    else:  # pragma: no cover - exercised by negative tests
        raise AssertionError(
            "illegal action rejection contract failed: bundle.illegal_action "
            "must raise a domain error during validate_action"
        )

    try:
        _apply(rules_engine, state, bundle.illegal_action)
    except ArenaCoreError:
        return
    else:  # pragma: no cover - exercised by negative tests
        raise AssertionError(
            "illegal action rejection contract failed: apply_action must defensively reject "
            "bundle.illegal_action"
        )


def assert_state_transition_behavior(bundle: GameContractBundle) -> None:
    """Assert that legal actions produce coherent transition results."""

    rules_engine = bundle.definition.rules_engine
    state = bundle.initial_state
    transition = _apply(rules_engine, state, bundle.legal_action)

    assert transition.state != state, (
        "state transition contract failed: applying a legal action must produce a new state"
    )
    assert isinstance(transition.events, tuple), (
        "state transition contract failed: emitted events must be exposed as an immutable tuple"
    )
    assert transition.result == rules_engine.result(transition.state), (
        "state transition contract failed: transition.result must match "
        "rules_engine.result(next_state)"
    )


def assert_terminal_result_consistency(bundle: GameContractBundle) -> None:
    """Assert that terminal fixtures and results stay coherent."""

    rules_engine = bundle.definition.rules_engine
    terminal_action = _terminal_action(bundle)
    transition = _apply(rules_engine, bundle.near_terminal_state, terminal_action)

    assert transition.state == bundle.terminal_state, (
        "terminal/result contract failed: near_terminal_state should reach terminal_state via "
        "bundle.terminal_action (defaulting to bundle.legal_action)"
    )
    assert rules_engine.is_terminal(bundle.terminal_state), (
        "terminal/result contract failed: terminal_state must be terminal"
    )
    assert transition.result == rules_engine.result(bundle.terminal_state), (
        "terminal/result contract failed: transition.result must match "
        "rules_engine.result(terminal_state)"
    )
    assert not rules_engine.legal_actions(
        bundle.terminal_state,
        rules_engine.current_seat(bundle.terminal_state),
    ), "terminal/result contract failed: terminal states must not expose legal actions"


def assert_serialization_round_trip(bundle: GameContractBundle) -> None:
    """Assert that serializer round-trips preserve game semantics."""

    serializer = bundle.definition.serializer
    rules_engine = bundle.definition.rules_engine

    assert isinstance(serializer, Serializer), (
        "serialization round-trip contract failed: game definition must expose a shared Serializer"
    )

    rehydrated_config = serializer.load_config(serializer.dump_config(bundle.config))
    assert rehydrated_config == bundle.config, (
        "serialization round-trip contract failed: config round-trip must "
        "preserve the validated config"
    )

    rehydrated_state = serializer.load_state(serializer.dump_state(bundle.near_terminal_state))
    assert _state_semantics_match(
        rules_engine,
        bundle.near_terminal_state,
        rehydrated_state,
    ), (
        "serialization round-trip contract failed: rehydrated state must "
        "behave like the original state"
    )

    rehydrated_action = serializer.load_action(serializer.dump_action(bundle.legal_action))
    assert rehydrated_action == bundle.legal_action, (
        "serialization round-trip contract failed: action round-trip must preserve the legal action"
    )

    observation = rules_engine.observation(
        bundle.initial_state,
        rules_engine.current_seat(bundle.initial_state),
    )
    rehydrated_observation = serializer.load_observation(serializer.dump_observation(observation))
    assert rehydrated_observation == observation, (
        "serialization round-trip contract failed: observation round-trip "
        "must preserve observation data"
    )


def assert_public_view_contract(bundle: GameContractBundle) -> None:
    """Assert that the game's public view is coherent and round-trips.

    For a perfect-information game the public view must equal the full state:
    that equality is what lets the spectator channel serve ``dump_state``
    directly. A game declaring ``has_hidden_information`` must instead redact,
    and must not simply return the full state under a different name.
    """

    definition = bundle.definition
    serializer = definition.serializer
    state = bundle.near_terminal_state

    public_payload = dump_public_state(serializer, state)
    assert isinstance(public_payload, dict), (
        "public view contract failed: dump_public_state must return a JSON mapping"
    )

    rehydrated = load_public_state(serializer, public_payload)
    assert rehydrated is not None, (
        "public view contract failed: load_public_state must rehydrate its own payload"
    )

    hidden = getattr(definition, "has_hidden_information", False)
    full_payload = serializer.dump_state(state)

    if not hidden:
        assert public_payload == full_payload, (
            "public view contract failed: a game without hidden information must expose "
            "a public view identical to its full state; if it genuinely redacts, it must "
            "declare has_hidden_information=True"
        )
        return

    assert public_payload != full_payload, (
        "public view contract failed: a game declaring has_hidden_information=True must "
        "actually redact — its public view is identical to its full state, which would "
        "leak private state to every spectator"
    )


@dataclass(frozen=True)
class PrivateVariant:
    """Two values that differ only in what ``blind_seat`` may not see.

    For states, ``state`` and ``variant`` are game states; for chance outcomes
    (``private_outcome_variants``) they are outcomes.
    """

    state: object
    variant: object
    blind_seat: int


def _visible_events(events: Sequence[object], viewer: object) -> list[dict]:
    from arena.match.transcript import dump_domain_event, filter_event_payloads

    return filter_event_payloads(
        [dump_domain_event(event).model_dump(mode="json") for event in events], viewer
    )


def _assert_indistinguishable(
    label: str, blind: int, pairs: dict[str, tuple[object, object]]
) -> None:
    for name, (a, b) in pairs.items():
        assert a == b, (
            f"seat view contract failed: {name} lets seat {blind} distinguish {label} "
            f"that differ only in information it may not see"
        )


def assert_seat_view_contract(bundle: GameContractBundle) -> None:
    """Assert that what each seat receives contains nothing it may not see.

    A perfect-information game's per-seat views must equal the full values.

    A hidden-information game is checked by **indistinguishability**. Each
    :class:`PrivateVariant` pairs two states that differ only in information its
    ``blind_seat`` may not see. Everything that seat receives must be identical
    across the pair: its state view, its observation (object and dump), its legal
    actions, the public view, the engine's ``public_state`` — and, one step on,
    the events and state view produced by every action legal in both. Variants
    must cover every seat as the blind one. Chance outcomes get the same
    treatment through ``private_outcome_variants`` applied at ``chance_state``.
    """

    definition = bundle.definition
    serializer = definition.serializer
    engine = definition.rules_engine
    state = bundle.near_terminal_state

    if not getattr(definition, "has_hidden_information", False):
        for seat in (0, 1):
            assert dump_state_for_seat(serializer, state, seat) == serializer.dump_state(state), (
                "seat view contract failed: a perfect-information game's per-seat state "
                "must equal its full state"
            )
            assert dump_config_for_seat(serializer, bundle.config, seat) == (
                serializer.dump_config(bundle.config)
            ), "seat view contract failed: per-seat config must equal the full config"
        assert dump_public_config(serializer, bundle.config) == (
            serializer.dump_config(bundle.config)
        ), "seat view contract failed: public config must equal the full config"
        return

    variants: Sequence[PrivateVariant] = getattr(bundle, "private_variants", None) or ()
    assert variants, (
        "seat view contract failed: a hidden-information game's bundle must supply "
        "private_variants"
    )
    assert {v.blind_seat for v in variants} == {0, 1}, (
        "seat view contract failed: private_variants must cover every seat as blind_seat"
    )

    # Actions that legitimately reveal private information to the table (Liar's
    # Dice "call" shows both hands): excluded from the one-step comparison,
    # because their whole point is that the result differs.
    revealing = tuple(getattr(bundle, "revealing_actions", ()) or ())
    for pv in variants:
        _assert_state_variant(engine, serializer, pv, revealing)

    if getattr(definition, "has_chance_nodes", False):
        chance_state = getattr(bundle, "chance_state", None)
        outcome_variants: Sequence[PrivateVariant] = (
            getattr(bundle, "private_outcome_variants", None) or ()
        )
        assert chance_state is not None and outcome_variants, (
            "seat view contract failed: a hidden-information game with chance nodes must "
            "supply chance_state and private_outcome_variants"
        )
        assert is_chance_node(engine, chance_state), (
            "seat view contract failed: chance_state must be at a chance node"
        )
        assert {v.blind_seat for v in outcome_variants} == {0, 1}, (
            "seat view contract failed: private_outcome_variants must cover every seat"
        )
        for ov in outcome_variants:
            _assert_outcome_variant(engine, serializer, chance_state, ov)


def _assert_state_variant(
    engine: object, serializer: object, pv: PrivateVariant, revealing: tuple[object, ...] = ()
) -> None:
    blind, a, b = pv.blind_seat, pv.state, pv.variant
    assert serializer.dump_state(a) != serializer.dump_state(b), (
        "seat view contract failed: a private variant must differ in its private information"
    )
    assert dump_state_for_seat(serializer, a, blind) != serializer.dump_state(a), (
        "seat view contract failed: a hidden-information game's per-seat state must "
        "redact the full state"
    )

    obs_a, obs_b = engine.observation(a, blind), engine.observation(b, blind)
    _assert_indistinguishable(
        "states",
        blind,
        {
            "dump_state_for_seat": (
                dump_state_for_seat(serializer, a, blind),
                dump_state_for_seat(serializer, b, blind),
            ),
            "the observation object": (obs_a, obs_b),
            "dump_observation": (
                serializer.dump_observation(obs_a),
                serializer.dump_observation(obs_b),
            ),
            "legal_actions": (engine.legal_actions(a, blind), engine.legal_actions(b, blind)),
            "dump_public_state": (
                dump_public_state(serializer, a),
                dump_public_state(serializer, b),
            ),
            "the engine's public_state": (public_state(engine, a), public_state(engine, b)),
        },
    )

    if engine.is_terminal(a) or is_chance_node(engine, a):
        return
    mover = engine.current_seat(a)
    assert mover == engine.current_seat(b), (
        f"seat view contract failed: whose turn it is lets seat {blind} distinguish states"
    )
    common = [x for x in engine.legal_actions(a, mover) if x in engine.legal_actions(b, mover)]
    for action in common:
        if action in revealing:
            continue
        ta, tb = engine.apply_action(a, mover, action), engine.apply_action(b, mover, action)
        _assert_indistinguishable(
            f"the results of {action!r}",
            blind,
            {
                **_views_after(engine, serializer, ta.state, tb.state, blind),
                "events": (_visible_events(ta.events, blind), _visible_events(tb.events, blind)),
                "public events": (
                    _visible_events(ta.events, None),
                    _visible_events(tb.events, None),
                ),
                "dump_state_for_seat after the move": (
                    dump_state_for_seat(serializer, ta.state, blind),
                    dump_state_for_seat(serializer, tb.state, blind),
                ),
                "dump_public_state after the move": (
                    dump_public_state(serializer, ta.state),
                    dump_public_state(serializer, tb.state),
                ),
            },
        )


def _views_after(
    engine: object, serializer: object, a: object, b: object, blind: int
) -> dict[str, tuple[object, object]]:
    """What the blind seat is sent about the resulting state: agents act on the
    observation (object and dump) and its legal actions, not the state view."""

    if engine.is_terminal(a) and engine.is_terminal(b):
        return {}
    obs_a, obs_b = engine.observation(a, blind), engine.observation(b, blind)
    return {
        "the observation object after it": (obs_a, obs_b),
        "dump_observation after it": (
            serializer.dump_observation(obs_a),
            serializer.dump_observation(obs_b),
        ),
        "legal_actions after it": (
            engine.legal_actions(a, blind),
            engine.legal_actions(b, blind),
        ),
    }


def _assert_outcome_variant(
    engine: object, serializer: object, chance_state: object, ov: PrivateVariant
) -> None:
    from arena.core.public_view import dump_chance_outcome_for_viewer

    blind, a, b = ov.blind_seat, ov.state, ov.variant
    assert serializer.dump_chance_outcome(a) != serializer.dump_chance_outcome(b), (
        "seat view contract failed: an outcome variant must differ in its private part"
    )
    ta, tb = engine.apply_chance(chance_state, a), engine.apply_chance(chance_state, b)
    _assert_indistinguishable(
        "chance outcomes",
        blind,
        {
            **_views_after(engine, serializer, ta.state, tb.state, blind),
            "dump_chance_outcome_for_seat": (
                dump_chance_outcome_for_viewer(serializer, a, blind),
                dump_chance_outcome_for_viewer(serializer, b, blind),
            ),
            "dump_public_chance_outcome": (
                dump_chance_outcome_for_viewer(serializer, a, None),
                dump_chance_outcome_for_viewer(serializer, b, None),
            ),
            "chance events": (
                _visible_events(ta.events, blind),
                _visible_events(tb.events, blind),
            ),
            "public chance events": (
                _visible_events(ta.events, None),
                _visible_events(tb.events, None),
            ),
            "dump_state_for_seat after the outcome": (
                dump_state_for_seat(serializer, ta.state, blind),
                dump_state_for_seat(serializer, tb.state, blind),
            ),
            "dump_public_state after the outcome": (
                dump_public_state(serializer, ta.state),
                dump_public_state(serializer, tb.state),
            ),
        },
    )


#: Steps a chance-contract playout takes before stopping; enough to reach
#: several chance nodes in any small game without making the suite slow.
_CHANCE_PLAYOUT_STEPS = 60


def _first_legal_playout(definition: object, seed: int) -> object:
    from arena.match import apply_match_action, start_match

    match = start_match(definition, definition.config_type(), seed=seed)
    engine = match.rules_engine
    for _ in range(_CHANCE_PLAYOUT_STEPS):
        if engine.is_terminal(match.state):
            break
        seat = engine.current_seat(match.state)
        match = apply_match_action(match, seat, engine.legal_actions(match.state, seat)[0])
    return match


def assert_chance_contract(bundle: GameContractBundle) -> None:
    """Assert determinism under a seed, replay without it, and seed secrecy.

    A no-op for a game without chance nodes. For one with them (Phase 37):

    * the same seed and the same actions reproduce the same transcript;
    * the transcript validates by replaying recorded outcomes — no seed needed;
    * the seed appears nowhere in the transcript, which carries every snapshot
      and event a seat or spectator would receive.
    """

    import json

    from arena.match import dump_match_transcript, validate_match_transcript

    definition = bundle.definition
    if not getattr(definition, "has_chance_nodes", False):
        return

    seed = 0x5EED_0FAC_0177_E570_1234_5678_9ABC_DEF0
    first = dump_match_transcript(_first_legal_playout(definition, seed))
    second = dump_match_transcript(_first_legal_playout(definition, seed))

    assert first == second, (
        "chance contract failed: the same seed and actions produced different transcripts"
    )
    assert any(turn["kind"] == "chance" for turn in first["turns"]), (
        "chance contract failed: a first-legal-action playout reached no chance node"
    )

    validate_match_transcript(definition, first)

    if not getattr(definition, "has_hidden_information", False):
        from arena.core.public_view import dump_chance_outcome_for_viewer

        playout = _first_legal_playout(definition, seed)
        for turn in playout.turns:
            if turn.kind != "chance":
                continue
            full = definition.serializer.dump_chance_outcome(turn.outcome)
            for viewer in (0, 1, None):
                assert dump_chance_outcome_for_viewer(
                    definition.serializer, turn.outcome, viewer
                ) == full, (
                    "chance contract failed: a perfect-information game must show every "
                    "viewer the whole chance outcome"
                )

    text = json.dumps(first)
    for fragment in (str(seed), f"{seed:x}", f"{seed:X}"):
        assert fragment not in text, (
            "chance contract failed: the seed is visible in the transcript"
        )


def assert_game_contract(bundle: GameContractBundle) -> None:
    """Run the full reusable contract suite against a game bundle."""

    assert_valid_initial_state(bundle)
    assert_legal_action_generation(bundle)
    assert_illegal_action_rejection(bundle)
    assert_state_transition_behavior(bundle)
    assert_terminal_result_consistency(bundle)
    assert_serialization_round_trip(bundle)
    assert_public_view_contract(bundle)
    assert_seat_view_contract(bundle)
    assert_chance_contract(bundle)


def _terminal_action(bundle: GameContractBundle) -> object:
    return getattr(bundle, "terminal_action", None) or bundle.legal_action


def _state_semantics_match(
    rules_engine: object,
    original_state: object,
    rehydrated_state: object,
) -> bool:
    """Compare public state semantics through the shared rules-engine contract."""

    original_is_terminal = rules_engine.is_terminal(original_state)
    rehydrated_is_terminal = rules_engine.is_terminal(rehydrated_state)
    if original_is_terminal != rehydrated_is_terminal:
        return False

    if rules_engine.result(original_state) != rules_engine.result(rehydrated_state):
        return False

    if original_is_terminal:
        return True

    original_seat = rules_engine.current_seat(original_state)
    rehydrated_seat = rules_engine.current_seat(rehydrated_state)
    if original_seat != rehydrated_seat:
        return False

    original_actions = rules_engine.legal_actions(original_state, original_seat)
    rehydrated_actions = rules_engine.legal_actions(rehydrated_state, rehydrated_seat)
    if original_actions != rehydrated_actions:
        return False

    original_observation = rules_engine.observation(original_state, original_seat)
    rehydrated_observation = rules_engine.observation(rehydrated_state, rehydrated_seat)
    return original_observation == rehydrated_observation


__all__: Sequence[str] = [
    "GameContractBundle",
    "PrivateVariant",
    "assert_chance_contract",
    "assert_game_contract",
    "assert_illegal_action_rejection",
    "assert_legal_action_generation",
    "assert_public_view_contract",
    "assert_seat_view_contract",
    "assert_serialization_round_trip",
    "assert_state_transition_behavior",
    "assert_terminal_result_consistency",
    "assert_valid_initial_state",
]
