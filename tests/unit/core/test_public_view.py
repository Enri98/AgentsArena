"""Public-view contract additions (Phase 36 Slice 1).

The spectator channel needs a notion of "what may be shown to someone who holds
no seat". For perfect-information games that is the full state, so the helpers
fall back to ``dump_state``. Games that genuinely redact must declare
``has_hidden_information`` and implement the hooks, and the registry rejects a
declaration that is not backed by an implementation.
"""

from __future__ import annotations

import dataclasses

import pytest

from arena.core.exceptions import IncompletePublicView
from arena.core.public_view import (
    dump_public_state,
    load_public_state,
    public_state,
    rules_engine_declares_public_state,
    serializer_declares_public_state,
    validate_public_view,
)
from arena.core.registry import GameRegistry
from arena.core.rules_engine import RulesEngine
from arena.core.serializer import Serializer
from arena.games import build_default_registry
from arena.testing.factories import build_fake_game_bundle

# ---------------------------------------------------------------------------
# Fallbacks: a game that says nothing gets the full state as its public view
# ---------------------------------------------------------------------------


def test_public_state_falls_back_to_seat_zero_observation() -> None:
    bundle = build_fake_game_bundle()
    engine = bundle.definition.rules_engine
    state = bundle.initial_state

    assert not rules_engine_declares_public_state(engine)
    assert public_state(engine, state) == engine.observation(state, 0)


def test_dump_and_load_public_state_fall_back_to_full_state() -> None:
    bundle = build_fake_game_bundle()
    serializer = bundle.definition.serializer
    state = bundle.near_terminal_state

    assert not serializer_declares_public_state(serializer)

    payload = dump_public_state(serializer, state)
    assert payload == serializer.dump_state(state)
    assert load_public_state(serializer, payload) == serializer.load_state(payload)


# ---------------------------------------------------------------------------
# Hooks: a game that redacts gets its own implementation used
# ---------------------------------------------------------------------------


class _RedactingEngine:
    """Minimal engine exposing only what the public-view helpers touch."""

    def observation(self, state: object, seat: int) -> str:
        return f"observation-for-{seat}"

    def public_state(self, state: object) -> str:
        return "redacted-public-view"


class _RedactingSerializer:
    def dump_state(self, state: object) -> dict[str, object]:
        return {"secret": "visible", "public": 1}

    def load_state(self, payload: dict[str, object]) -> str:
        return "full"

    def dump_public_state(self, state: object) -> dict[str, object]:
        return {"public": 1}

    def load_public_state(self, payload: dict[str, object]) -> str:
        return "public"


def test_declared_hooks_are_preferred_over_the_fallback() -> None:
    engine = _RedactingEngine()
    serializer = _RedactingSerializer()

    assert rules_engine_declares_public_state(engine)
    assert serializer_declares_public_state(serializer)

    assert public_state(engine, object()) == "redacted-public-view"
    assert dump_public_state(serializer, object()) == {"public": 1}
    assert load_public_state(serializer, {"public": 1}) == "public"


def test_redacted_payload_omits_private_fields() -> None:
    serializer = _RedactingSerializer()
    state = object()

    assert "secret" in serializer.dump_state(state)
    assert "secret" not in dump_public_state(serializer, state)


# ---------------------------------------------------------------------------
# The declaration gate
# ---------------------------------------------------------------------------


def _definition(**overrides: object) -> object:
    bundle = build_fake_game_bundle()
    return dataclasses.replace(bundle.definition, **overrides)


def test_perfect_information_games_need_no_hooks() -> None:
    validate_public_view(_definition())  # does not raise


def test_declaring_hidden_information_without_hooks_is_rejected() -> None:
    definition = _definition(has_hidden_information=True)

    with pytest.raises(IncompletePublicView) as exc:
        validate_public_view(definition)

    missing = exc.value.details["missing"]
    assert "rules_engine.public_state" in missing
    assert "serializer.dump_public_state" in missing
    assert "serializer.load_public_state" in missing


def test_partial_implementation_names_only_what_is_missing() -> None:
    definition = _definition(
        has_hidden_information=True,
        rules_engine=_RedactingEngine(),
    )

    with pytest.raises(IncompletePublicView) as exc:
        validate_public_view(definition)

    missing = exc.value.details["missing"]
    assert "rules_engine.public_state" not in missing
    assert "serializer.dump_public_state" in missing


def test_fully_implemented_hidden_information_game_validates() -> None:
    definition = _definition(
        has_hidden_information=True,
        rules_engine=_RedactingEngine(),
        serializer=_RedactingSerializer(),
    )
    validate_public_view(definition)  # does not raise


def test_registry_rejects_an_unbacked_declaration() -> None:
    registry = GameRegistry()

    with pytest.raises(IncompletePublicView):
        registry.register(_definition(has_hidden_information=True))

    assert registry.list() == ()


# ---------------------------------------------------------------------------
# Additivity: the change must not break existing Protocol conformance
# ---------------------------------------------------------------------------


def test_existing_engines_and_serializers_still_satisfy_their_protocols() -> None:
    """The helpers are free functions precisely so this stays true.

    Adding public_state to the runtime_checkable RulesEngine Protocol would
    make every existing engine fail isinstance until it implemented the method.
    """

    for definition in build_default_registry().list():
        assert isinstance(definition.rules_engine, RulesEngine)
        assert isinstance(definition.serializer, Serializer)


def test_shipped_games_declare_no_hidden_information() -> None:
    for definition in build_default_registry().list():
        assert definition.has_hidden_information is False


def test_shipped_games_expose_their_full_state_as_the_public_view() -> None:
    """This equality is what makes the Phase 36 spectator channel safe."""

    for definition in build_default_registry().list():
        state = definition.rules_engine.initial_state(definition.config_type())
        assert dump_public_state(definition.serializer, state) == definition.serializer.dump_state(
            state
        )
