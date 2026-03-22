"""Tests for core exception contracts."""

from __future__ import annotations

import inspect

from arena.core.exceptions import (
    ArenaCoreError,
    ConfigError,
    DuplicateGameRegistration,
    GameFinished,
    IllegalAction,
    InvalidGameConfig,
    RehydrationError,
    RulesError,
    SerializationError,
    UnknownGame,
    WrongPlayer,
)


def test_exception_symbols_are_importable() -> None:
    assert ArenaCoreError.__name__ == "ArenaCoreError"
    assert InvalidGameConfig.__name__ == "InvalidGameConfig"
    assert DuplicateGameRegistration.__name__ == "DuplicateGameRegistration"


def test_exception_hierarchy_matches_phase_one_contract() -> None:
    assert issubclass(ConfigError, ArenaCoreError)
    assert issubclass(InvalidGameConfig, ConfigError)
    assert issubclass(RulesError, ArenaCoreError)
    assert issubclass(WrongPlayer, RulesError)
    assert issubclass(IllegalAction, RulesError)
    assert issubclass(GameFinished, RulesError)
    assert issubclass(SerializationError, ArenaCoreError)
    assert issubclass(RehydrationError, SerializationError)
    assert issubclass(UnknownGame, ArenaCoreError)
    assert issubclass(DuplicateGameRegistration, ArenaCoreError)


def test_exception_payload_contract_uses_code_and_optional_details() -> None:
    error = IllegalAction(
        "column is full",
        details={"column": 3},
    )

    assert str(error) == "column is full"
    assert error.message == "column is full"
    assert error.code == "illegal_action"
    assert error.details == {"column": 3}


def test_exception_payload_contract_allows_custom_code() -> None:
    error = ArenaCoreError(
        "custom failure",
        code="custom_error",
        details={"reason": "example"},
    )

    assert error.code == "custom_error"
    assert error.details == {"reason": "example"}


def test_exception_defaults_message_to_class_name() -> None:
    error = UnknownGame()

    assert str(error) == "UnknownGame"
    assert error.message == "UnknownGame"
    assert error.code == "unknown_game"
    assert error.details is None


def test_exception_module_stays_game_agnostic() -> None:
    source = inspect.getsource(__import__("arena.core.exceptions", fromlist=["*"]))

    assert "connect4" not in source.lower()
    assert "stale" not in source.lower()
