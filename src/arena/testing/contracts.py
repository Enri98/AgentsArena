"""Reusable contract assertions for game implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from arena.core.chance import is_chance_node
from arena.core.exceptions import ArenaCoreError
from arena.core.public_view import (
    dump_config_for_seat,
    dump_public_config,
    dump_public_state,
    dump_state_for_seat,
    load_public_state,
)
from arena.core.seats import is_seat
from arena.core.serializer import Serializer


@runtime_checkable
class GameContractBundle(Protocol):
    """Fixture bundle contract used by the shared game-contract assertions.

    A hidden-information game's bundle must also define
    ``private_variant_state`` and ``private_variant_blind_seat``: a state equal to
    ``near_terminal_state`` except for information the blind seat may not see.
    See :func:`assert_seat_view_contract`.

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
        # to move until the match resolves it, so the bundle supplies a settled
        # post-opening state instead; the rest of this contract checks that one.
        initial_state = bundle.initial_state
        assert not is_chance_node(rules_engine, initial_state), (
            "initial state contract failed: for a game that opens at a chance node, "
            "bundle.initial_state must be a settled state after the opening resolves"
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
        rules_engine.apply_action(state, seat, bundle.illegal_action)
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
    seat = rules_engine.current_seat(state)
    transition = rules_engine.apply_action(state, seat, bundle.legal_action)

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
    near_terminal_seat = rules_engine.current_seat(bundle.near_terminal_state)
    terminal_action = _terminal_action(bundle)
    transition = rules_engine.apply_action(
        bundle.near_terminal_state,
        near_terminal_seat,
        terminal_action,
    )

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


def assert_seat_view_contract(bundle: GameContractBundle) -> None:
    """Assert that what each seat receives contains nothing it may not see.

    A perfect-information game's per-seat views must equal the full state and
    config. A hidden-information game is checked by **indistinguishability**: the
    bundle's ``private_variant_state`` differs from ``near_terminal_state`` only in
    information ``private_variant_blind_seat`` is not entitled to, so everything
    that seat receives — its state view, its observation, and the public view —
    must be byte-identical between the two. Any field that let the seat tell them
    apart would be a leak.
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

    variant = getattr(bundle, "private_variant_state", None)
    blind = getattr(bundle, "private_variant_blind_seat", None)
    assert variant is not None and blind is not None, (
        "seat view contract failed: a hidden-information game's bundle must supply "
        "private_variant_state and private_variant_blind_seat"
    )
    assert serializer.dump_state(variant) != serializer.dump_state(state), (
        "seat view contract failed: private_variant_state must differ from "
        "near_terminal_state in its private information"
    )

    views = {
        "dump_state_for_seat": lambda s: dump_state_for_seat(serializer, s, blind),
        "dump_observation": lambda s: serializer.dump_observation(engine.observation(s, blind)),
        "dump_public_state": lambda s: dump_public_state(serializer, s),
    }
    for name, view in views.items():
        assert view(state) == view(variant), (
            f"seat view contract failed: {name} lets seat {blind} distinguish states "
            f"that differ only in information it may not see"
        )

    assert dump_state_for_seat(serializer, state, blind) != serializer.dump_state(state), (
        "seat view contract failed: a hidden-information game's per-seat state must "
        "redact the full state"
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
