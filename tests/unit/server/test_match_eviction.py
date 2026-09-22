"""MatchRegistry eviction (Phase 36 Slice 0).

MatchRegistry previously held every Match for the process lifetime, along with
the per-match dicts on app.state.  Spectators hold sockets against dead matches,
so eviction had to land before the spectator endpoint opened.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from arena.games import build_default_registry
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from arena.server.registry import MatchRegistry

#: Matches here are created but never played. At the 30 s production per-turn
#: default an abandoned match parks run_match for 30 s, and those leaked drivers
#: made the suite flaky. Phase 36 Slice 2's match-owned driver is the real fix.
_SHORT_MATCH = {
    "game_id": "connect4",
    "per_turn_deadline_ms": 2000,
    "disconnect_grace_ms": 500,
}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _registry(clock: _Clock, **kwargs: Any) -> MatchRegistry:
    return MatchRegistry(build_default_registry(), time_fn=clock, **kwargs)


def _create(registry: MatchRegistry, game_id: str = "connect4") -> str:
    match = registry.create(
        game_id=game_id,
        game_config_payload=None,
        players_spec=[{"label": "a"}, {"label": "b"}],
        per_turn_deadline_ms=30000,
        per_action_retry_budget=3,
        disconnect_grace_ms=30000,
    )
    return match.match_id


def _make_terminal(registry: MatchRegistry, match_id: str) -> None:
    match = registry.get(match_id)
    match.session = match.arena.abort_session(match.session)


# ---------------------------------------------------------------------------
# Lifecycle-aware sweeping
# ---------------------------------------------------------------------------


def test_non_terminal_match_survives_until_max_age() -> None:
    clock = _Clock()
    registry = _registry(clock, max_age_s=100.0, retention_s=10.0)
    match_id = _create(registry)

    clock.advance(99.0)
    assert registry.evict_expired() == ()
    assert registry.get(match_id) is not None

    clock.advance(2.0)
    assert registry.evict_expired() == (match_id,)
    assert registry.list_match_ids() == ()


def test_terminal_match_is_kept_for_retention_then_evicted() -> None:
    clock = _Clock()
    registry = _registry(clock, retention_s=50.0, max_age_s=100_000.0)
    match_id = _create(registry)
    _make_terminal(registry, match_id)

    clock.advance(49.0)
    assert registry.evict_expired() == ()

    clock.advance(2.0)
    assert registry.evict_expired() == (match_id,)


def test_terminal_match_evicts_sooner_than_an_abandoned_one() -> None:
    """Retention and max-age are independent knobs, keyed on lifecycle."""

    clock = _Clock()
    registry = _registry(clock, retention_s=10.0, max_age_s=1000.0)
    finished = _create(registry)
    running = _create(registry)
    _make_terminal(registry, finished)

    clock.advance(20.0)
    assert registry.evict_expired() == (finished,)
    assert registry.list_match_ids() == (running,)


# ---------------------------------------------------------------------------
# Overflow ceiling
# ---------------------------------------------------------------------------


def test_overflow_sheds_oldest_matches() -> None:
    clock = _Clock()
    registry = _registry(clock, max_matches=3, retention_s=1e9, max_age_s=1e9)

    ids = []
    for _ in range(3):
        ids.append(_create(registry))
        clock.advance(1.0)

    assert set(registry.list_match_ids()) == set(ids)

    newest = _create(registry)
    remaining = set(registry.list_match_ids())

    assert len(remaining) == 3
    assert ids[0] not in remaining  # oldest shed
    assert newest in remaining


# ---------------------------------------------------------------------------
# Explicit delete and the eviction hook
# ---------------------------------------------------------------------------


def test_delete_reports_presence_and_fires_hook() -> None:
    clock = _Clock()
    evicted: list[str] = []
    registry = _registry(clock, on_evict=evicted.append)
    match_id = _create(registry)

    assert registry.delete(match_id) is True
    assert evicted == [match_id]

    assert registry.delete(match_id) is False
    assert evicted == [match_id]  # no duplicate notification


def test_sweep_fires_hook_for_each_evicted_match() -> None:
    clock = _Clock()
    evicted: list[str] = []
    registry = _registry(clock, max_age_s=10.0, on_evict=evicted.append)
    first = _create(registry)
    second = _create(registry)

    clock.advance(20.0)
    registry.evict_expired()

    assert sorted(evicted) == sorted([first, second])


def test_a_failing_hook_does_not_break_eviction() -> None:
    clock = _Clock()

    def _boom(match_id: str) -> None:
        raise RuntimeError("hook exploded")

    registry = _registry(clock, max_age_s=10.0, on_evict=_boom)
    match_id = _create(registry)

    clock.advance(20.0)
    assert registry.evict_expired() == (match_id,)
    assert registry.list_match_ids() == ()


def test_create_triggers_a_sweep() -> None:
    """No background task: creation is the sweep trigger."""

    clock = _Clock()
    registry = _registry(clock, max_age_s=10.0)
    stale = _create(registry)

    clock.advance(20.0)
    fresh = _create(registry)

    assert registry.list_match_ids() == (fresh,)
    assert stale not in registry.list_match_ids()


# ---------------------------------------------------------------------------
# App wiring: eviction releases the per-match state kept outside the registry
# ---------------------------------------------------------------------------


def test_eviction_releases_app_state_and_rate_limiter_counters() -> None:
    limiter = RateLimiter.unlimited()
    app = create_app(rate_limiter=limiter)
    with TestClient(app, raise_server_exceptions=False) as client:
        match_id = client.post("/matches", json=_SHORT_MATCH).json()["match_id"]

    # Simulate the per-match bookkeeping the WS handlers create lazily.
    app.state._ws_seat_slots = {match_id: {0: None, 1: None}}
    app.state._ws_done_events = {match_id: object()}
    limiter.acquire_connection(ip="1.2.3.4", match_id=match_id)
    assert limiter.connection_count(match_id=match_id) == 1

    assert app.state.match_registry.delete(match_id) is True

    assert match_id not in app.state._ws_seat_slots
    assert match_id not in app.state._ws_done_events
    assert limiter.connection_count(match_id=match_id) == 0


# ---------------------------------------------------------------------------
# Protocol §11 gate: hidden-information games cannot be served on the v1 wire
# ---------------------------------------------------------------------------


def test_hidden_information_game_is_refused_until_phase_38() -> None:
    """The v1 wire broadcasts one full snapshot to both seats.

    Serving a game that declares hidden information over it would leak private
    state, so match creation refuses rather than leaking. Phase 38 lifts this.
    """

    import dataclasses

    import pytest

    from arena.core.registry import GameRegistry
    from arena.server.errors import InvalidConfig

    class _RedactingEngine:
        def observation(self, state: object, seat: int) -> str:
            return "obs"

        def public_state(self, state: object) -> str:
            return "public"

    class _RedactingSerializer:
        def dump_state(self, state: object) -> dict[str, object]:
            return {"secret": 1, "public": 2}

        def load_state(self, payload: dict[str, object]) -> str:
            return "full"

        def dump_public_state(self, state: object) -> dict[str, object]:
            return {"public": 2}

        def load_public_state(self, payload: dict[str, object]) -> str:
            return "public"

    source = build_default_registry().get("connect4")
    hidden = dataclasses.replace(
        source,
        game_id="hidden-game",
        has_hidden_information=True,
        rules_engine=_RedactingEngine(),
        serializer=_RedactingSerializer(),
    )
    games = GameRegistry()
    games.register(hidden)

    registry = MatchRegistry(games)
    with pytest.raises(InvalidConfig) as exc:
        registry.create(
            game_id="hidden-game",
            game_config_payload=None,
            players_spec=[{"label": "a"}, {"label": "b"}],
            per_turn_deadline_ms=30000,
            per_action_retry_budget=3,
            disconnect_grace_ms=30000,
        )
    assert exc.value.details["reason"] == "hidden_information_unsupported"
