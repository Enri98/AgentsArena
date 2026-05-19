"""Real WebSocket session connecting to arena.server."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as _ws_connect
from websockets.exceptions import ConnectionClosed

from arena.adapters.websocket.codec import dumps, loads
from arena.adapters.websocket.envelope import (
    ActionResponseEnvelope,
    HelloEnvelope,
    PongEnvelope,
)
from arena.adapters.websocket.messages import (
    ActionResponseBody,
    HelloBody,
    PongBody,
    WelcomeBody,
)
from arena.sdk._events import (
    ErrorEvent,
    MatchAbortedEvent,
    MatchFinishedEvent,
    MatchStateEvent,
    ObservationEvent,
    SdkEvent,
    TurnCommittedEvent,
    WelcomeEvent,
)
from arena.sdk.errors import HandshakeError, ProtocolError, close_code_to_error

CLIENT_NAME = "arena-sdk-python"
CLIENT_VERSION = "0.1.0"
SUPPORTED_SCHEMA_VERSIONS = [1]


class Session:
    """Low-level WebSocket session. Exposes recv() / send_action() loop form."""

    def __init__(self, ws: ClientConnection, welcome: WelcomeBody) -> None:
        self._ws = ws
        self._welcome = welcome

    @classmethod
    async def connect(
        cls,
        url: str,
        seat: int,
        *,
        resume_token: str | None = None,
    ) -> "Session":
        """Open WS, perform hello/welcome handshake, return connected Session.

        Raises:
            HandshakeError: if welcome is not received or seat mismatch.
            ProtocolError subclass: if the server closes with a 4xxx code.
        """
        try:
            ws = await _ws_connect(url, ping_interval=None)
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else 1006
            reason = exc.rcvd.reason if exc.rcvd else "connection failed"
            raise close_code_to_error(code, reason) from exc

        # Send hello
        hello = HelloEnvelope(
            schema_version=1,
            seat=seat,
            payload=HelloBody(
                client_name=CLIENT_NAME,
                client_version=CLIENT_VERSION,
                supported_schema_versions=SUPPORTED_SCHEMA_VERSIONS,
                auth=None,
                requested_seat=seat,
                resume_token=resume_token,
            ),
        )
        try:
            await ws.send(dumps(hello))
            raw = await ws.recv()
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else 1006
            reason = exc.rcvd.reason if exc.rcvd else "connection closed"
            raise close_code_to_error(code, reason) from exc

        env = loads(raw)
        if env.type != "welcome":
            await ws.close()
            raise HandshakeError(f"Expected welcome, got {env.type!r}")

        welcome: WelcomeBody = env.payload  # type: ignore[assignment]
        if welcome.seat != seat:
            await ws.close()
            raise HandshakeError(
                f"Server assigned seat {welcome.seat}, requested {seat}"
            )

        return cls(ws, welcome)

    async def recv(self) -> SdkEvent:
        """Receive the next meaningful event from the server.

        Ping messages are auto-replied and skipped (transparent heartbeat).
        Returns an SdkEvent subclass.
        Raises ProtocolError subclass on abnormal close.
        """
        while True:
            try:
                raw = await self._ws.recv()
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else 1006
                reason = exc.rcvd.reason if exc.rcvd else "connection closed"
                raise close_code_to_error(code, reason) from exc

            env = loads(raw)

            if env.type == "ping":
                pong = PongEnvelope(
                    schema_version=1,
                    match_id=env.match_id,
                    payload=PongBody(nonce=env.payload.nonce),  # type: ignore[union-attr]
                )
                await self._ws.send(dumps(pong))
                continue

            return _env_to_event(env)

    async def send_action(
        self,
        action: dict[str, Any],
        *,
        turn_id: str | None = None,
    ) -> None:
        """Send an action_response envelope.

        Generates a fresh UUID4 turn_id if not provided.
        """
        tid = turn_id or str(uuid.uuid4())
        body = ActionResponseBody.model_validate({
            "action_response": {
                "game_id": self._welcome.game_id,
                "schema_version": 1,
                "seat": self._welcome.seat,
                "action": action,
            }
        })
        env = ActionResponseEnvelope(
            schema_version=1,
            match_id=self._welcome.match_id,
            seat=self._welcome.seat,
            turn_id=tid,
            payload=body,
        )
        try:
            await self._ws.send(dumps(env))
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else 1006
            reason = exc.rcvd.reason if exc.rcvd else "connection closed"
            raise close_code_to_error(code, reason) from exc

    @classmethod
    async def reconnect(
        cls,
        url: str,
        seat: int,
        resume_token: str,
    ) -> "Session":
        """Reconnect to a match using a resume_token from a prior session.

        Sends a hello envelope that includes the resume_token, triggering the
        server's reconnect path (§8 of NETWORK_PROTOCOL.md).  On success the
        server rotates the token and delivers a fresh welcome with a new
        resume_token that the caller should store for future reconnects.

        Raises:
            HandshakeError: if welcome is not received or seat mismatch.
            ProtocolError subclass: on WS close with a 4xxx code.
        """
        return await cls.connect(url, seat, resume_token=resume_token)

    async def close(self) -> None:
        await self._ws.close()

    async def __aenter__(self) -> "Session":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    # Properties echoed from welcome
    # ------------------------------------------------------------------ #

    @property
    def match_id(self) -> str:
        return self._welcome.match_id

    @property
    def seat(self) -> int:
        return self._welcome.seat

    @property
    def game_id(self) -> str:
        return self._welcome.game_id

    @property
    def welcome(self) -> WelcomeBody:
        return self._welcome


def _env_to_event(env: object) -> SdkEvent:  # type: ignore[return]
    """Convert a WireEnvelope to an SdkEvent. Raises if type is unhandled."""
    t = getattr(env, "type", None)
    payload = getattr(env, "payload", None)

    if t == "welcome":
        return WelcomeEvent(body=payload)
    if t == "observation_request":
        return ObservationEvent(body=payload)
    if t == "turn_committed":
        return TurnCommittedEvent(body=payload)
    if t == "match_state":
        return MatchStateEvent(body=payload)
    if t == "match_finished":
        return MatchFinishedEvent(body=payload)
    if t == "match_aborted":
        return MatchAbortedEvent(body=payload)
    if t == "error":
        return ErrorEvent(body=payload)
    raise ProtocolError(0, f"Unhandled envelope type: {t!r}")


__all__: Sequence[str] = [
    "CLIENT_NAME",
    "CLIENT_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "Session",
    "_env_to_event",
]
