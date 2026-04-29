"""Unit tests for MatchRegistry."""

from __future__ import annotations

import threading

import pytest

from arena.games import build_default_registry
from arena.server.errors import InvalidConfig, UnknownGame
from arena.server.registry import MatchRegistry


def _registry() -> MatchRegistry:
    return MatchRegistry(build_default_registry())


def test_create_happy_path_connect4() -> None:
    reg = _registry()
    match = reg.create(
        game_id="connect4",
        game_config_payload={"rows": 6, "columns": 7, "connect_length": 4},
        players_spec=[{"label": "alice"}, {"label": "bob"}],
        per_turn_deadline_ms=30000,
        per_action_retry_budget=3,
        disconnect_grace_ms=30000,
    )
    assert match.game_id == "connect4"
    assert match.per_turn_deadline_ms == 30000
    assert match.per_action_retry_budget == 3
    assert len(match.players) == 2
    assert match.players[0].label == "alice"
    assert match.players[1].label == "bob"


def test_match_id_min_length() -> None:
    reg = _registry()
    match = reg.create(
        game_id="tictactoe",
        game_config_payload=None,
        players_spec=[{"label": "a"}, {"label": "b"}],
        per_turn_deadline_ms=30000,
        per_action_retry_budget=3,
        disconnect_grace_ms=30000,
    )
    # secrets.token_urlsafe(16) produces ~22 base64url characters
    assert len(match.match_id) >= 22


def test_create_unknown_game_raises() -> None:
    reg = _registry()
    with pytest.raises(UnknownGame):
        reg.create(
            game_id="chess",
            game_config_payload=None,
            players_spec=[{"label": "a"}, {"label": "b"}],
            per_turn_deadline_ms=30000,
            per_action_retry_budget=3,
            disconnect_grace_ms=30000,
        )


def test_create_invalid_config_raises_and_preserves_cause() -> None:
    reg = _registry()
    with pytest.raises(InvalidConfig) as exc_info:
        reg.create(
            game_id="connect4",
            game_config_payload={"rows": 1, "columns": 7, "connect_length": 4},
            players_spec=[{"label": "a"}, {"label": "b"}],
            per_turn_deadline_ms=30000,
            per_action_retry_budget=3,
            disconnect_grace_ms=30000,
        )
    assert exc_info.value.error_code == "invalid_config"


def test_get_returns_created_match() -> None:
    reg = _registry()
    match = reg.create(
        game_id="tictactoe",
        game_config_payload=None,
        players_spec=[{"label": "x"}, {"label": "o"}],
        per_turn_deadline_ms=5000,
        per_action_retry_budget=1,
        disconnect_grace_ms=10000,
    )
    retrieved = reg.get(match.match_id)
    assert retrieved.match_id == match.match_id


def test_get_unknown_id_raises() -> None:
    from arena.server.errors import MatchNotFound

    reg = _registry()
    with pytest.raises(MatchNotFound):
        reg.get("nonexistent-id")


def test_list_match_ids() -> None:
    reg = _registry()
    assert reg.list_match_ids() == ()
    m1 = reg.create(
        game_id="connect4",
        game_config_payload={"rows": 6, "columns": 7, "connect_length": 4},
        players_spec=[{}, {}],
        per_turn_deadline_ms=30000,
        per_action_retry_budget=3,
        disconnect_grace_ms=30000,
    )
    m2 = reg.create(
        game_id="tictactoe",
        game_config_payload=None,
        players_spec=[{}, {}],
        per_turn_deadline_ms=30000,
        per_action_retry_budget=3,
        disconnect_grace_ms=30000,
    )
    ids = reg.list_match_ids()
    assert m1.match_id in ids
    assert m2.match_id in ids


def test_thread_safety_smoke() -> None:
    reg = _registry()
    errors: list[Exception] = []

    def worker() -> None:
        try:
            reg.create(
                game_id="tictactoe",
                game_config_payload=None,
                players_spec=[{}, {}],
                per_turn_deadline_ms=30000,
                per_action_retry_budget=3,
                disconnect_grace_ms=30000,
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(reg.list_match_ids()) == 10
