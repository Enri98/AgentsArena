"""LocalSession: in-memory session for unit testing choose() callbacks."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from arena.adapters.websocket.messages import WelcomeBody
from arena.sdk._events import SdkEvent
from arena.sdk._session import _env_to_event


class LocalSession:
    """In-memory session that replays a pre-scripted list of server envelopes.

    Use this in unit tests to drive your choose() callback without spinning up
    a real WebSocket server.

    Example::

        from arena.sdk.testing import LocalSession
        from arena.adapters.websocket.envelope import ObservationRequestEnvelope
        from arena.adapters.websocket.messages import ObservationRequestBody
        ...
        session = LocalSession(
            match_id="test",
            game_id="connect4",
            seat=0,
            server_script=[obs_env, match_finished_env],
        )
        event = await session.recv()   # ObservationEvent
        await session.send_action({"column": 3})
        event = await session.recv()   # MatchFinishedEvent
    """

    def __init__(
        self,
        *,
        match_id: str = "local-test-match",
        game_id: str = "connect4",
        seat: int = 0,
        server_script: list,  # list[WireEnvelope]
        schema_version: int = 1,
        per_turn_deadline_ms: int = 30000,
        per_action_retry_budget: int = 3,
        disconnect_grace_ms: int = 30000,
        players: list | None = None,
    ) -> None:
        self._match_id = match_id
        self._game_id = game_id
        self._seat = seat
        self._inbox: list = list(server_script)
        self._sent_actions: list[dict[str, Any]] = []
        self._sent_turn_ids: list[str] = []

        # Build a synthetic WelcomeBody
        self._welcome = WelcomeBody.model_validate({
            "match_id": match_id,
            "game_id": game_id,
            "game_schema_version": 1,
            "seat": seat,
            "lifecycle": "running",
            "schema_version": schema_version,
            "negotiated_schema_version": schema_version,
            "resume_token": None,
            "per_turn_deadline_ms": per_turn_deadline_ms,
            "per_action_retry_budget": per_action_retry_budget,
            "disconnect_grace_ms": disconnect_grace_ms,
            "players": players or [
                {"player_id": "p0", "label": "player0", "seat": 0},
                {"player_id": "p1", "label": "player1", "seat": 1},
            ],
            "match_config": {},
        })

    async def recv(self) -> SdkEvent:
        """Pop the next envelope from the script and return it as an SdkEvent.

        Raises StopAsyncIteration when the script is exhausted.
        """
        if not self._inbox:
            raise StopAsyncIteration("LocalSession script exhausted")
        env = self._inbox.pop(0)
        return _env_to_event(env)

    async def send_action(
        self,
        action: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> None:
        """Record an action (does not send over the network)."""
        tid = turn_id or str(uuid.uuid4())
        self._sent_actions.append(action)
        self._sent_turn_ids.append(tid)

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "LocalSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        pass

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @property
    def match_id(self) -> str:
        return self._match_id

    @property
    def seat(self) -> int:
        return self._seat

    @property
    def game_id(self) -> str:
        return self._game_id

    @property
    def welcome(self) -> WelcomeBody:
        return self._welcome

    @property
    def sent_actions(self) -> list[dict[str, Any]]:
        """Actions sent via send_action(), in order."""
        return list(self._sent_actions)

    @property
    def sent_turn_ids(self) -> list[str]:
        return list(self._sent_turn_ids)


__all__: Sequence[str] = ["LocalSession"]
