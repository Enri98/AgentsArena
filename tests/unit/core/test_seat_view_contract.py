"""The indistinguishability contract catches leaks (Phase 38).

Each leaky game here passed the first version of ``assert_seat_view_contract``;
an adversarial review of Phase 38 Slice 1 found them. The contract now checks
every seat as the blind one, several states, one step onward, chance outcomes,
events, observation objects, and the engine's ``public_state``.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, replace

import pytest

from arena.core.public_view import (
    check_viewer,
    dump_chance_outcome_for_viewer,
    dump_state_for_seat,
    dump_state_for_viewer,
)
from arena.match import build_snapshot_for_viewer
from arena.testing import assert_game_contract, assert_seat_view_contract
from arena.testing.contracts import assert_valid_initial_state
from arena.testing.hidden_factory import (
    SecretReceived,
    SecretsDeal,
    SecretsDealt,
    SecretsObservation,
    SecretsPass,
    SecretsRulesEngine,
    SecretsSerializer,
    SecretsState,
    build_secrets_contract_bundle,
    build_secrets_game_definition,
)


def _bundle_with(*, serializer=None, engine=None, **fields):
    bundle = build_secrets_contract_bundle()
    definition = dataclasses.replace(
        bundle.definition,
        serializer=serializer or bundle.definition.serializer,
        rules_engine=engine or bundle.definition.rules_engine,
    )
    return dataclasses.replace(bundle, definition=definition, **fields)


def test_the_secrets_game_passes_the_full_contract() -> None:
    assert_game_contract(build_secrets_contract_bundle())


# -- leaks the first version missed ----------------------------------------


class _SeatOneSeesAll(SecretsSerializer):
    def dump_state_for_seat(self, state, seat):
        if seat == 1:
            return {**self.dump_state(state), "seat": 1}
        return super().dump_state_for_seat(state, seat)


class _PublicShowsSeatZero(SecretsSerializer):
    def dump_public_state(self, state):
        return {**super().dump_public_state(state), "s0": state.secrets and state.secrets[0]}


class _OutcomesWhole(SecretsSerializer):
    def dump_chance_outcome_for_seat(self, outcome, seat):
        return self.dump_chance_outcome(outcome)

    def dump_public_chance_outcome(self, outcome):
        return self.dump_chance_outcome(outcome)


@dataclass(frozen=True)
class _LeakyObservation(SecretsObservation):
    opp: int | None = None


class _ObservationObjectLeaks(SecretsRulesEngine):
    def observation(self, state, seat):
        base = super().observation(state, seat)
        other = state.secrets[1 - seat] if state.secrets else None
        return _LeakyObservation(
            seat=base.seat, turn=base.turn, my_secret=base.my_secret, opp=other
        )


class _LeaksOnOwnTurn(SecretsRulesEngine):
    def observation(self, state, seat):
        obs = super().observation(state, seat)
        if state.secrets and seat == self.current_seat(state) and not self.is_terminal(state):
            return replace(obs, my_secret=obs.my_secret * 100 + state.secrets[1 - seat])
        return obs


class _EnginePublicStateIsFull(SecretsRulesEngine):
    def public_state(self, state):
        return state


@dataclass(frozen=True)
class _LeakyDealt(SecretsDealt):
    secrets: list[int] = dataclasses.field(default_factory=list)


class _DealEventLeaks(SecretsRulesEngine):
    def apply_chance(self, state, outcome):
        transition = super().apply_chance(state, outcome)
        return replace(transition, events=(_LeakyDealt(secrets=list(outcome.secrets)),))


@dataclass(frozen=True)
class _PublicSecret(SecretReceived):
    def visible_to(self, viewer):
        return True


class _PrivateEventMadePublic(SecretsRulesEngine):
    def apply_chance(self, state, outcome):
        transition = super().apply_chance(state, outcome)
        return replace(
            transition,
            events=tuple(
                _PublicSecret(seat=e.seat, secret=e.secret) if isinstance(e, SecretReceived) else e
                for e in transition.events
            ),
        )


@pytest.mark.parametrize(
    ("overrides", "leak"),
    [
        ({"serializer": _SeatOneSeesAll()}, "dump_state_for_seat lets seat 1"),
        ({"serializer": _PublicShowsSeatZero()}, "dump_public_state lets seat 1"),
        ({"serializer": _OutcomesWhole()}, "dump_chance_outcome_for_seat"),
        ({"engine": _ObservationObjectLeaks()}, "the observation object"),
        ({"engine": _LeaksOnOwnTurn()}, "the observation object"),
        ({"engine": _EnginePublicStateIsFull()}, "the engine's public_state"),
        ({"engine": _DealEventLeaks()}, "chance events"),
        ({"engine": _PrivateEventMadePublic()}, "chance events"),
    ],
)
def test_a_leak_through_any_channel_fails_the_contract(overrides: dict, leak: str) -> None:
    with pytest.raises(AssertionError, match=leak):
        assert_seat_view_contract(_bundle_with(**overrides))


def test_variants_must_cover_every_seat() -> None:
    bundle = build_secrets_contract_bundle()
    one_sided = tuple(v for v in bundle.private_variants if v.blind_seat == 0)
    with pytest.raises(AssertionError, match="every seat"):
        assert_seat_view_contract(dataclasses.replace(bundle, private_variants=one_sided))


def test_a_hidden_game_bundle_must_supply_variants() -> None:
    bundle = build_secrets_contract_bundle()
    with pytest.raises(AssertionError, match="private_variants"):
        assert_seat_view_contract(dataclasses.replace(bundle, private_variants=()))
    with pytest.raises(AssertionError, match="private_outcome_variants"):
        assert_seat_view_contract(dataclasses.replace(bundle, private_outcome_variants=()))


def test_a_constant_extra_observation_field_is_not_a_leak() -> None:
    class _Constant(SecretsSerializer):
        def dump_observation(self, observation):
            return {**super().dump_observation(observation), "debug": "same-for-everyone"}

    assert_seat_view_contract(_bundle_with(serializer=_Constant()))


# -- the opening-chance initial state is derived, not asserted -------------


def test_the_opening_must_be_reached_through_opening_outcomes() -> None:
    class _IgnoresConfig(SecretsRulesEngine):
        def initial_state(self, config):
            return SecretsState(turn=0, max_turns=999)

    with pytest.raises(AssertionError, match="did not reproduce"):
        assert_valid_initial_state(_bundle_with(engine=_IgnoresConfig()))

    with pytest.raises(AssertionError, match="opening_outcomes"):
        assert_valid_initial_state(_bundle_with(opening_outcomes=()))


# -- viewers are seats or None, nothing else -------------------------------


@pytest.mark.parametrize("viewer", [-1, 2, True, False, "0", 0.0])
def test_bogus_viewers_are_rejected(viewer: object) -> None:
    definition = build_secrets_game_definition()
    state = SecretsState(turn=1, max_turns=2, secrets=(3, 8))
    with pytest.raises(ValueError):
        check_viewer(viewer)
    with pytest.raises(ValueError):
        dump_state_for_viewer(definition.serializer, state, viewer)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_snapshot_for_viewer(definition, definition.config_type(), state, viewer)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        dump_chance_outcome_for_viewer(definition.serializer, SecretsDeal((3, 8)), viewer)


def test_dump_state_for_seat_needs_a_seat() -> None:
    with pytest.raises(ValueError):
        dump_state_for_seat(SecretsSerializer(), SecretsState(1, 2, (3, 8)), None)  # type: ignore[arg-type]


# -- adversarial review of Slices 2-3 --------------------------------------


class _LeaksNextTurnObservation(SecretsRulesEngine):
    """Clean at every variant state; leaks in the observation one move later."""

    def observation(self, state, seat):
        obs = super().observation(state, seat)
        if state.secrets and state.turn >= 2 and not self.is_terminal(state):
            return replace(obs, my_secret=obs.my_secret * 100 + state.secrets[1 - seat])
        return obs


def test_an_observation_leak_one_step_on_fails_the_contract() -> None:
    bundle = build_secrets_contract_bundle()
    # Keep only variants at turn 1, so the leak can only be seen after a move.
    variants = tuple(v for v in bundle.private_variants if v.state.turn == 1)
    early = dataclasses.replace(
        _bundle_with(engine=_LeaksNextTurnObservation()), private_variants=variants
    )
    early = dataclasses.replace(
        early,
        private_variants=tuple(
            dataclasses.replace(
                v,
                state=replace(v.state, max_turns=4),
                variant=replace(v.variant, max_turns=4),
            )
            for v in variants
        ),
    )
    with pytest.raises(AssertionError, match="after it"):
        assert_seat_view_contract(early)


@dataclass(frozen=True)
class _Reveal(SecretsPass):
    """A showdown: tells the table both digits."""


@dataclass(frozen=True)
class _HandsRevealed(SecretsDealt):
    secrets: list[int] = dataclasses.field(default_factory=list)


class _WithShowdown(SecretsRulesEngine):
    def legal_actions(self, state, seat):
        base = super().legal_actions(state, seat)
        return base + (_Reveal(),) if base else base

    def validate_action(self, state, seat, action):
        if isinstance(action, _Reveal):
            return super().validate_action(state, seat, SecretsPass())
        return super().validate_action(state, seat, action)

    def apply_action(self, state, seat, action):
        transition = super().apply_action(state, seat, SecretsPass())
        if isinstance(action, _Reveal):
            return replace(
                transition,
                events=transition.events + (_HandsRevealed(secrets=list(state.secrets)),),
            )
        return transition


def test_a_declared_showdown_is_not_a_leak() -> None:
    """Liar's Dice's "call" legitimately reveals both hands to the table."""

    with pytest.raises(AssertionError, match="Reveal"):
        assert_seat_view_contract(_bundle_with(engine=_WithShowdown()))
    assert_seat_view_contract(
        _bundle_with(engine=_WithShowdown(), revealing_actions=(_Reveal(),))
    )
