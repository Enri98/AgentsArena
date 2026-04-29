"""MatchRegistry and Match: server-layer match bookkeeping."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from arena.core.exceptions import ArenaCoreError
from arena.core.exceptions import UnknownGame as CoreUnknownGame
from arena.core.registry import GameRegistry
from arena.runtime.models import PlayerRecord
from arena.runtime.session import Arena, MatchSession
from arena.server.errors import InvalidConfig, MatchNotFound, UnknownGame


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


class MatchRegistry:
    """Thread-safe registry of all active Match records."""

    def __init__(self, game_registry: GameRegistry) -> None:
        self._game_registry = game_registry
        self._matches: dict[str, Match] = {}
        self._lock = threading.Lock()

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

        arena = Arena()
        session = arena.create_session(
            definition=definition,
            config=config,
            players=list(players),
            policy_bindings={},
        )

        match_id = secrets.token_urlsafe(16)
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
            created_at=time.monotonic(),
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
