"""SessionRegistry — tracks active arena.sdk Sessions for MCP tool handlers."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from arena.sdk import Session
from arena.sdk._events import (
    MatchAbortedEvent,
    MatchFinishedEvent,
    MatchStateEvent,
    SdkEvent,
    TurnCommittedEvent,
)
from arena.sdk.errors import MatchAbortedError, ProtocolError


@dataclass
class SessionHandle:
    """Holds a live Session together with its event buffers."""

    session: Session
    queue: asyncio.Queue[SdkEvent]
    history: list[SdkEvent]
    last_state: MatchStateEvent | None
    recv_task: asyncio.Task[None]
    lifecycle: str  # "running" | "finished" | "aborted"

    def to_status_dict(self) -> dict[str, Any]:
        state_body: dict[str, Any] = {}
        if self.last_state is not None:
            raw = self.last_state.body
            if hasattr(raw, "model_dump"):
                state_body = raw.model_dump(mode="json")
            else:
                state_body = dict(raw.__dict__) if hasattr(raw, "__dict__") else {}
        return {"lifecycle": self.lifecycle, **state_body}


class SessionRegistry:
    """Registry mapping (match_id, seat) -> SessionHandle.

    Manages background recv loops and auto-purges entries on terminal events.
    """

    def __init__(self) -> None:
        self._handles: dict[tuple[str, int], SessionHandle] = {}

    async def register(
        self,
        server_url: str,
        seat: int,
        resume_token: str | None = None,
    ) -> str:
        """Connect a Session, start its recv loop, return the match_id."""
        session = await Session.connect(server_url, seat, resume_token=resume_token)
        match_id = session.match_id
        queue: asyncio.Queue[SdkEvent] = asyncio.Queue()

        # Build handle with a sentinel task; replace before storing in registry
        async def _noop() -> None:
            pass

        handle = SessionHandle(
            session=session,
            queue=queue,
            history=[],
            last_state=None,
            recv_task=asyncio.get_event_loop().create_task(_noop()),
            lifecycle="running",
        )
        # Create the real recv task now that the handle dataclass exists
        task = asyncio.get_event_loop().create_task(
            self._recv_loop(match_id, seat, handle)
        )
        handle.recv_task = task
        self._handles[(match_id, seat)] = handle
        return match_id

    def get(self, match_id: str, seat: int) -> SessionHandle:
        """Return the handle for (match_id, seat); raise KeyError if absent."""
        return self._handles[(match_id, seat)]

    async def close(self, match_id: str, seat: int) -> None:
        """Cancel the recv task, close the session, remove the registry entry."""
        handle = self._handles.pop((match_id, seat), None)
        if handle is None:
            return
        handle.recv_task.cancel()
        try:
            await asyncio.wait_for(handle.recv_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        try:
            await handle.session.close()
        except Exception:
            pass

    async def _recv_loop(
        self,
        match_id: str,
        seat: int,
        handle: SessionHandle,
    ) -> None:
        """Background loop that drains events from the session into the handle buffers."""

        def _log_warning(msg: str) -> None:
            logging.getLogger(__name__).warning(msg)

        try:
            while True:
                try:
                    event = await handle.session.recv()
                except MatchAbortedError as exc:
                    handle.lifecycle = "aborted"
                    _log_warning(
                        f"[arena.mcp] match {match_id} seat {seat} aborted: {exc}"
                    )
                    self._handles.pop((match_id, seat), None)
                    return
                except ProtocolError as exc:
                    handle.lifecycle = "aborted"
                    _log_warning(
                        f"[arena.mcp] match {match_id} seat {seat} protocol error: {exc}"
                    )
                    self._handles.pop((match_id, seat), None)
                    return
                except Exception as exc:
                    _log_warning(
                        f"[arena.mcp] match {match_id} seat {seat} recv error: {exc}"
                    )
                    return

                # Buffer in queue for awaiting tools
                await handle.queue.put(event)

                # Update state snapshot
                if isinstance(event, MatchStateEvent):
                    handle.last_state = event

                # Accumulate history
                if isinstance(event, (TurnCommittedEvent, MatchFinishedEvent, MatchAbortedEvent)):
                    handle.history.append(event)

                # Terminal events: update lifecycle and remove from registry
                if isinstance(event, MatchFinishedEvent):
                    handle.lifecycle = "finished"
                    self._handles.pop((match_id, seat), None)
                    return
                if isinstance(event, MatchAbortedEvent):
                    handle.lifecycle = "aborted"
                    self._handles.pop((match_id, seat), None)
                    return

        except asyncio.CancelledError:
            return
