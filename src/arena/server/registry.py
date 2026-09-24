"""MatchRegistry and Match: server-layer match bookkeeping."""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from arena.core.exceptions import ArenaCoreError
from arena.core.exceptions import UnknownGame as CoreUnknownGame
from arena.core.registry import GameRegistry
from arena.runtime.models import PlayerRecord
from arena.runtime.session import Arena, MatchSession
from arena.server.config import (
    MATCH_MAX_AGE_S,
    MATCH_RETENTION_S,
    MATCH_UNSTARTED_MAX_AGE_S,
    MAX_TRACKED_MATCHES,
)
from arena.server.errors import InvalidConfig, MatchNotFound, ServerBusy, UnknownGame


@dataclass
class Match:
    """Server-layer record for one hosted match."""

    match_id: str
    game_id: str
    definition: Any
    match_config: Any
    players: tuple[PlayerRecord, ...]
    arena: Arena
    session: MatchSession
    per_turn_deadline_ms: int
    per_action_retry_budget: int
    disconnect_grace_ms: int
    created_at: float
    # Phase 32: resume tokens rotated on every welcome/reconnect.
    # seat → current valid token; set by send_welcome before being sent to the client.
    resume_tokens: dict[int, str] = field(default_factory=dict)


_TERMINAL_LIFECYCLES = frozenset({"finished", "aborted"})


class MatchRegistry:
    """Thread-safe registry of all active Match records.

    Matches are evicted on a sweep triggered by :meth:`create`, so no background
    task is needed.  Eviction notifies ``on_evict`` so the caller can release
    whatever else it keys by ``match_id`` — the per-match dicts on ``app.state``
    and the rate limiter's per-match counters.
    """

    def __init__(
        self,
        game_registry: GameRegistry,
        *,
        retention_s: float = MATCH_RETENTION_S,
        max_age_s: float = MATCH_MAX_AGE_S,
        unstarted_max_age_s: float = MATCH_UNSTARTED_MAX_AGE_S,
        max_matches: int = MAX_TRACKED_MATCHES,
        time_fn: Callable[[], float] = time.monotonic,
        on_evict: Callable[[str], None] | None = None,
    ) -> None:
        self._game_registry = game_registry
        self._matches: dict[str, Match] = {}
        self._lock = threading.Lock()
        self._retention_s = retention_s
        self._max_age_s = max_age_s
        self._unstarted_max_age_s = min(unstarted_max_age_s, max_age_s)
        self._max_matches = max_matches
        self._now = time_fn
        self._on_evict = on_evict

    def create(
        self,
        *,
        game_id: str,
        game_config_payload: dict[str, Any] | None,
        players_spec: list[dict[str, Any]],
        per_turn_deadline_ms: int,
        per_action_retry_budget: int,
        disconnect_grace_ms: int,
    ) -> Match:
        """Validate inputs, build a MatchSession, and register the Match."""

        try:
            definition = self._game_registry.get(game_id)
        except CoreUnknownGame as exc:
            raise UnknownGame(str(exc)) from exc

        # Phase 38 lifted the §11 gate that refused hidden-information games:
        # every snapshot, event, chance outcome, transcript and welcome config is
        # now built per recipient (see runtime_bridge._broadcast_per_viewer).

        raw_config = game_config_payload if game_config_payload is not None else {}
        try:
            if raw_config:
                config = definition.serializer.load_config(raw_config)
            else:
                config = definition.config_type()
        except ArenaCoreError as exc:
            raise InvalidConfig(str(exc), details=exc.details) from exc
        except Exception as exc:
            raise InvalidConfig(str(exc)) from exc

        players = tuple(
            PlayerRecord(
                player_id=f"p{i}",
                seat=i,
                label=spec.get("label") or None,
            )
            for i, spec in enumerate(players_spec)
        )

        # One id everywhere: the session used to mint its own, so envelopes
        # built from session.match_id disagreed with welcome and GET /matches.
        match_id = secrets.token_urlsafe(16)
        arena = Arena()
        session = arena.create_session(
            definition=definition,
            config=config,
            players=list(players),
            policy_bindings={},
            match_id=match_id,
        )

        # Make room before admitting: a full registry sheds what it can, and
        # refuses rather than evict a match someone is playing.
        self.evict_expired()
        with self._lock:
            if len(self._matches) >= self._max_matches:
                raise ServerBusy(
                    "The server is at its match capacity; try again later."
                )

        match = Match(
            match_id=match_id,
            game_id=game_id,
            definition=definition,
            match_config=config,
            players=players,
            arena=arena,
            session=session,
            per_turn_deadline_ms=per_turn_deadline_ms,
            per_action_retry_budget=per_action_retry_budget,
            disconnect_grace_ms=disconnect_grace_ms,
            created_at=self._now(),
        )

        with self._lock:
            self._matches[match_id] = match

        return match

    def get(self, match_id: str) -> Match:
        with self._lock:
            match = self._matches.get(match_id)
        if match is None:
            raise MatchNotFound(f"Match '{match_id}' not found.")
        return match

    def list_match_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._matches.keys())

    # ── Eviction ───────────────────────────────────────────────────────────

    def delete(self, match_id: str) -> bool:
        """Drop one match. Returns whether it was present."""

        with self._lock:
            existed = self._matches.pop(match_id, None) is not None
        if existed:
            self._notify_evicted(match_id)
        return existed

    def evict_expired(self) -> tuple[str, ...]:
        """Sweep expired matches, and make room below ``max_matches``.

        Terminal matches are kept for ``retention_s`` so a late reader can still
        fetch the result; never-started ones for ``unstarted_max_age_s``;
        running ones are presumed abandoned after ``max_age_s``. At or over
        ``max_matches``, terminal matches are shed first, then never-started
        ones, oldest first, until there is room for one more. A running match is
        never shed for room: that let anyone creating matches push a live one
        out, its seats' resume tokens with it.
        """

        now = self._now()
        with self._lock:
            doomed: list[str] = []
            for match_id, match in self._matches.items():
                age = now - match.created_at
                lifecycle = self._lifecycle(match)
                if lifecycle in _TERMINAL_LIFECYCLES:
                    limit = self._retention_s
                elif lifecycle == "created":
                    limit = self._unstarted_max_age_s
                else:
                    limit = self._max_age_s
                if age >= limit:
                    doomed.append(match_id)

            for match_id in doomed:
                self._matches.pop(match_id, None)

            overflow = len(self._matches) - self._max_matches + 1
            if overflow > 0:
                sheddable = sorted(
                    (
                        (0 if self._lifecycle(m) in _TERMINAL_LIFECYCLES else 1, m.created_at, mid)
                        for mid, m in self._matches.items()
                        if self._lifecycle(m) in _TERMINAL_LIFECYCLES
                        or self._lifecycle(m) == "created"
                    )
                )
                for _, _, match_id in sheddable[:overflow]:
                    self._matches.pop(match_id, None)
                    doomed.append(match_id)

        for match_id in doomed:
            self._notify_evicted(match_id)
        return tuple(doomed)

    @staticmethod
    def _lifecycle(match: Match) -> str:
        return str(getattr(match.session.lifecycle, "value", match.session.lifecycle))

    def _notify_evicted(self, match_id: str) -> None:
        if self._on_evict is None:
            return
        try:
            self._on_evict(match_id)
        except Exception:  # pragma: no cover - a bad hook must not break eviction
            pass
