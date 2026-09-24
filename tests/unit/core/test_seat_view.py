"""Per-seat views: state, config, and chance outcomes (Phase 38 Slice 1).

For a perfect-information game every view is the full value. A hidden-information
game must redact, and the shared contract proves it by indistinguishability: two
states differing only in what a seat may not see must look identical to it.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from arena.core.exceptions import IncompletePublicView
from arena.core.public_view import (
    dump_chance_outcome_for_viewer,
    dump_config_for_seat,
    dump_config_for_viewer,
    dump_public_config,
    dump_state_for_seat,
    dump_state_for_viewer,
    validate_public_view,
)
from arena.core.registry import GameRegistry
from arena.games.pig import PigConfig, PigGameDefinition, PigState
from arena.match import build_snapshot_for_viewer, start_match
from arena.testing import assert_game_contract, assert_seat_view_contract
from arena.testing.chance_factory import CoinOutcome, build_coin_game_definition
from arena.testing.hidden_factory import (
    SecretsDeal,
    SecretsSerializer,
    SecretsState,
    build_secrets_contract_bundle,
    build_secrets_game_definition,
)

SECRETS = build_secrets_game_definition()
STATE = SecretsState(turn=1, max_turns=2, secrets=(3, 8))

# ---------------------------------------------------------------------------
# Fallbacks: a perfect-information game's views are the full value
# ---------------------------------------------------------------------------


def test_perfect_information_views_fall_back_to_the_full_value() -> None:
    serializer = PigGameDefinition.serializer
    state = PigState(scores=(4, 9), current_seat=1, turn_total=3, roll_pending=False,
                     target_score=50)
    config = PigConfig(target_score=30)

    for viewer in (0, 1, None):
        assert dump_state_for_viewer(serializer, state, viewer) == serializer.dump_state(state)
        assert dump_config_for_viewer(serializer, config, viewer) == serializer.dump_config(config)


def test_perfect_information_outcomes_are_shown_whole() -> None:
    serializer = build_coin_game_definition().serializer
    for viewer in (0, 1, None):
        assert dump_chance_outcome_for_viewer(serializer, CoinOutcome(face=1), viewer) == {
            "face": 1
        }


# ---------------------------------------------------------------------------
# Hooks: a hidden-information game redacts
# ---------------------------------------------------------------------------


def test_each_seat_sees_only_its_own_secret() -> None:
    serializer = SECRETS.serializer
    assert dump_state_for_seat(serializer, STATE, 0)["my_secret"] == 3
    assert dump_state_for_seat(serializer, STATE, 1)["my_secret"] == 8
    for seat in (0, 1):
        assert "secrets" not in dump_state_for_seat(serializer, STATE, seat)
    assert "secrets" not in dump_state_for_viewer(serializer, STATE, None)


def test_a_private_deal_is_split_per_seat_and_hidden_from_the_public() -> None:
    serializer = SECRETS.serializer
    deal = SecretsDeal(secrets=(3, 8))
    assert dump_chance_outcome_for_viewer(serializer, deal, 0) == {"my_secret": 3}
    assert dump_chance_outcome_for_viewer(serializer, deal, 1) == {"my_secret": 8}
    assert dump_chance_outcome_for_viewer(serializer, deal, None) == {}


def test_config_hooks_are_optional_and_used_when_present() -> None:
    class _Redacting(SecretsSerializer):
        def dump_config_for_seat(self, config: object, seat: int) -> dict:
            return {"seat_view": seat}

        def dump_public_config(self, config: object) -> dict:
            return {"public": True}

    config = SECRETS.config_type()
    assert dump_config_for_seat(SECRETS.serializer, config, 0) == {"max_turns": 2}
    assert dump_config_for_seat(_Redacting(), config, 1) == {"seat_view": 1}
    assert dump_public_config(_Redacting(), config) == {"public": True}


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def test_perfect_information_viewer_snapshots_equal_the_authoritative_one() -> None:
    match = start_match(PigGameDefinition, PigConfig())
    for viewer in (0, 1, None):
        snapshot = build_snapshot_for_viewer(
            PigGameDefinition, match.config, match.state, viewer
        )
        assert snapshot == match.initial_snapshot


def test_viewer_snapshots_of_a_hidden_game_redact() -> None:
    match = start_match(SECRETS, SECRETS.config_type(), seed=42)
    secrets = match.state.secrets
    assert secrets is not None

    seat_0 = build_snapshot_for_viewer(SECRETS, match.config, match.state, 0)
    public = build_snapshot_for_viewer(SECRETS, match.config, match.state, None)

    assert seat_0.state["my_secret"] == secrets[0]
    assert "secrets" not in seat_0.state and "secrets" not in public.state
    assert "my_secret" not in public.state
    # The authoritative snapshot still has everything: it is what replay checks.
    assert match.turns[-1].post_snapshot.state["secrets"] == list(secrets)


# ---------------------------------------------------------------------------
# The declaration gate
# ---------------------------------------------------------------------------


class _NoSeatHook(SecretsSerializer):
    dump_state_for_seat = None  # type: ignore[assignment]


class _NoOutcomeHooks(SecretsSerializer):
    dump_chance_outcome_for_seat = None  # type: ignore[assignment]
    dump_public_chance_outcome = None  # type: ignore[assignment]


def test_a_hidden_game_must_implement_the_per_seat_state_hook() -> None:
    with pytest.raises(IncompletePublicView) as exc:
        validate_public_view(dataclasses.replace(SECRETS, serializer=_NoSeatHook()))
    assert exc.value.details["missing"] == ["serializer.dump_state_for_seat"]


def test_a_hidden_chance_game_must_redact_its_outcomes() -> None:
    with pytest.raises(IncompletePublicView) as exc:
        validate_public_view(dataclasses.replace(SECRETS, serializer=_NoOutcomeHooks()))
    assert exc.value.details["missing"] == [
        "serializer.dump_chance_outcome_for_seat",
        "serializer.dump_public_chance_outcome",
    ]


def test_the_secrets_game_registers() -> None:
    registry = GameRegistry()
    registry.register(SECRETS)
    assert registry.get("secrets-game") is SECRETS


# ---------------------------------------------------------------------------
# The shared contract catches leaks
# ---------------------------------------------------------------------------


def test_the_secrets_game_passes_the_full_contract() -> None:
    assert_game_contract(build_secrets_contract_bundle())


class _LeakyObservation(SecretsSerializer):
    def dump_observation(self, observation: object) -> dict:
        payload = super().dump_observation(observation)
        payload["debug"] = "opponent-secret-leaked"
        return payload


class _LeakyEngine(type(SECRETS.rules_engine)):  # type: ignore[misc]
    def observation(self, state, seat):  # type: ignore[no-untyped-def]
        obs = super().observation(state, seat)
        other = state.secrets[1 - seat] if state.secrets else None
        return dataclasses.replace(obs, turn=obs.turn * 100 + (other or 0))


class _LeakySeatState(SecretsSerializer):
    def dump_state_for_seat(self, state: object, seat: int) -> dict:
        return {**super().dump_state_for_seat(state, seat), "all": json.dumps(
            self.dump_state(state))}


class _LeakyPublic(SecretsSerializer):
    def dump_public_state(self, state: object) -> dict:
        return self.dump_state(state)


def _bundle_with(**definition_overrides: object):
    bundle = build_secrets_contract_bundle()
    return dataclasses.replace(
        bundle, definition=dataclasses.replace(bundle.definition, **definition_overrides)
    )


@pytest.mark.parametrize(
    ("overrides", "leak"),
    [
        ({"rules_engine": _LeakyEngine()}, "dump_observation"),
        ({"serializer": _LeakySeatState()}, "dump_state_for_seat"),
        ({"serializer": _LeakyPublic()}, "dump_public_state"),
    ],
)
def test_a_leak_through_any_view_fails_the_contract(overrides: dict, leak: str) -> None:
    with pytest.raises(AssertionError, match=leak):
        assert_seat_view_contract(_bundle_with(**overrides))


def test_an_observation_field_that_does_not_leak_passes() -> None:
    """A constant extra field is not a leak — it cannot distinguish the states."""

    assert_seat_view_contract(_bundle_with(serializer=_LeakyObservation()))


def test_a_hidden_game_bundle_must_supply_a_private_variant() -> None:
    bundle = build_secrets_contract_bundle()
    stripped = dataclasses.replace(bundle, private_variant_state=None)
    with pytest.raises(AssertionError, match="private_variant_state"):
        assert_seat_view_contract(stripped)
