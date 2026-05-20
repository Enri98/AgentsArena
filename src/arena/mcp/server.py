"""MCP server with 5 arena.sdk tools: join_match, get_observation, make_move,
get_history, match_status."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import mcp.types as types
from mcp.server import Server

from arena.mcp.session_registry import SessionRegistry
from arena.sdk._events import (
    ErrorEvent,
    MatchAbortedEvent,
    MatchFinishedEvent,
    ObservationEvent,
    TurnCommittedEvent,
)
from arena.sdk.errors import SdkError

_DEFAULT_OBS_TIMEOUT = 30.0


def _text(data: Any) -> list[types.TextContent]:
    """Wrap a dict/list/str as a single TextContent JSON block."""
    if isinstance(data, str):
        return [types.TextContent(type="text", text=data)]
    return [types.TextContent(type="text", text=json.dumps(data))]


def _error_result(code: str, message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=_text({"error": True, "code": code, "message": message}),
        isError=True,
    )


def _ok_result(data: Any) -> types.CallToolResult:
    return types.CallToolResult(content=_text(data))


def _event_to_dict(event: Any) -> dict[str, Any]:
    """Convert an SdkEvent to a plain dict for JSON serialisation."""
    body = getattr(event, "body", event)
    if hasattr(body, "model_dump"):
        return body.model_dump(mode="json")
    if hasattr(body, "__dict__"):
        return dict(body.__dict__)
    return {"repr": repr(body)}


def build_server(registry: SessionRegistry | None = None) -> Server:
    """Construct and wire the MCP Server with 5 arena tools."""

    if registry is None:
        registry = SessionRegistry()

    server: Server = Server("arena-mcp")

    # ------------------------------------------------------------------ #
    # Tool listing
    # ------------------------------------------------------------------ #

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="join_match",
                description=(
                    "Join an arena match as a given seat. Returns match_id, seat, "
                    "game_id and welcome info."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "server_url": {
                            "type": "string",
                            "description": "WebSocket URL (ws:// or wss://) for this seat.",
                        },
                        "seat": {"type": "integer", "description": "Seat index (0 or 1)."},
                        "resume_token": {
                            "type": "string",
                            "description": "Optional resume token for reconnect.",
                        },
                    },
                    "required": ["server_url", "seat"],
                },
            ),
            types.Tool(
                name="get_observation",
                description=(
                    "Wait for the next ObservationEvent from the server. "
                    "Returns the observation body dict."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "match_id": {"type": "string"},
                        "seat": {"type": "integer"},
                        "timeout": {
                            "type": "number",
                            "description": "Seconds to wait (default 30).",
                        },
                    },
                    "required": ["match_id", "seat"],
                },
            ),
            types.Tool(
                name="make_move",
                description=(
                    "Send an action and wait for a TurnCommittedEvent or ErrorEvent. "
                    "Returns the event body dict."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "match_id": {"type": "string"},
                        "seat": {"type": "integer"},
                        "action": {
                            "type": "object",
                            "description": "Game-specific action dict (e.g. {\"column\": 3}).",
                        },
                        "turn_id": {"type": "string", "description": "Optional turn UUID."},
                    },
                    "required": ["match_id", "seat", "action"],
                },
            ),
            types.Tool(
                name="get_history",
                description=(
                    "Return the accumulated event history (all TurnCommitted + terminal event) "
                    "as a list of dicts."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "match_id": {"type": "string"},
                        "seat": {"type": "integer"},
                    },
                    "required": ["match_id", "seat"],
                },
            ),
            types.Tool(
                name="match_status",
                description=(
                    "Return the last seen MatchStateEvent body plus a lifecycle field."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "match_id": {"type": "string"},
                        "seat": {"type": "integer"},
                    },
                    "required": ["match_id", "seat"],
                },
            ),
        ]

    # ------------------------------------------------------------------ #
    # Tool dispatch
    # ------------------------------------------------------------------ #

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        try:
            if name == "join_match":
                return await _join_match(registry, arguments)
            elif name == "get_observation":
                return await _get_observation(registry, arguments)
            elif name == "make_move":
                return await _make_move(registry, arguments)
            elif name == "get_history":
                return await _get_history(registry, arguments)
            elif name == "match_status":
                return await _match_status(registry, arguments)
            else:
                return _error_result("unknown_tool", f"Unknown tool: {name!r}")
        except Exception as exc:
            logging.getLogger(__name__).warning("[arena.mcp] tool %s failed: %s", name, exc)
            return _error_result("internal_error", str(exc))

    return server


# ------------------------------------------------------------------ #
# Individual tool implementations (module-level private helpers)
# ------------------------------------------------------------------ #


async def _join_match(
    registry: SessionRegistry,
    args: dict[str, Any],
) -> types.CallToolResult:
    server_url = args.get("server_url")
    seat = args.get("seat")
    resume_token = args.get("resume_token")

    if not isinstance(server_url, str) or not server_url:
        return _error_result("invalid_args", "server_url must be a non-empty string")
    if not isinstance(seat, int):
        return _error_result("invalid_args", "seat must be an integer")

    try:
        match_id = await registry.register(server_url, seat, resume_token=resume_token)
    except SdkError as exc:
        return _error_result("sdk_error", str(exc))

    handle = registry.get(match_id, seat)
    welcome = handle.session.welcome
    welcome_dict: dict[str, Any]
    if hasattr(welcome, "model_dump"):
        welcome_dict = welcome.model_dump(mode="json")
    elif hasattr(welcome, "__dict__"):
        welcome_dict = dict(welcome.__dict__)
    else:
        welcome_dict = {}

    return _ok_result({
        "match_id": match_id,
        "seat": seat,
        "game_id": handle.session.game_id,
        "welcome": welcome_dict,
    })


async def _get_observation(
    registry: SessionRegistry,
    args: dict[str, Any],
) -> types.CallToolResult:
    match_id = args.get("match_id")
    seat = args.get("seat")
    timeout: float = float(args.get("timeout", _DEFAULT_OBS_TIMEOUT))

    if not isinstance(match_id, str):
        return _error_result("invalid_args", "match_id must be a string")
    if not isinstance(seat, int):
        return _error_result("invalid_args", "seat must be an integer")

    # Try to get the handle — it may have been purged if match already finished
    try:
        handle = registry.get(match_id, seat)
    except KeyError:
        return _error_result("no_session", f"No active session for match {match_id} seat {seat}")

    # If already finished/aborted, return terminal state
    if handle.lifecycle in ("finished", "aborted"):
        return _ok_result(handle.to_status_dict())

    # Drain the queue looking for an ObservationEvent; buffer others back
    deferred: list[Any] = []
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                # Re-enqueue deferred
                for e in deferred:
                    await handle.queue.put(e)
                return _error_result("timeout", "Timed out waiting for observation")
            try:
                event = await asyncio.wait_for(handle.queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                for e in deferred:
                    await handle.queue.put(e)
                return _error_result("timeout", "Timed out waiting for observation")

            if isinstance(event, ObservationEvent):
                for e in deferred:
                    await handle.queue.put(e)
                return _ok_result(_event_to_dict(event))
            elif isinstance(event, (MatchFinishedEvent, MatchAbortedEvent)):
                for e in deferred:
                    await handle.queue.put(e)
                lifecycle = "finished" if isinstance(event, MatchFinishedEvent) else "aborted"
                result = _event_to_dict(event)
                result["lifecycle"] = lifecycle
                return _ok_result(result)
            else:
                deferred.append(event)
    except Exception as exc:
        return _error_result("internal_error", str(exc))


async def _make_move(
    registry: SessionRegistry,
    args: dict[str, Any],
) -> types.CallToolResult:
    match_id = args.get("match_id")
    seat = args.get("seat")
    action = args.get("action")
    turn_id = args.get("turn_id")

    if not isinstance(match_id, str):
        return _error_result("invalid_args", "match_id must be a string")
    if not isinstance(seat, int):
        return _error_result("invalid_args", "seat must be an integer")
    if not isinstance(action, dict):
        return _error_result("invalid_args", "action must be a dict")

    try:
        handle = registry.get(match_id, seat)
    except KeyError:
        return _error_result("no_session", f"No active session for match {match_id} seat {seat}")

    try:
        await handle.session.send_action(action, turn_id=turn_id)
    except SdkError as exc:
        return _error_result("sdk_error", str(exc))

    # Wait for TurnCommittedEvent, ErrorEvent, or terminal event
    deferred: list[Any] = []
    try:
        deadline = asyncio.get_event_loop().time() + _DEFAULT_OBS_TIMEOUT
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                for e in deferred:
                    await handle.queue.put(e)
                return _error_result("timeout", "Timed out waiting for turn confirmation")
            try:
                event = await asyncio.wait_for(handle.queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                for e in deferred:
                    await handle.queue.put(e)
                return _error_result("timeout", "Timed out waiting for turn confirmation")

            if isinstance(event, (TurnCommittedEvent, ErrorEvent)):
                for e in deferred:
                    await handle.queue.put(e)
                return _ok_result(_event_to_dict(event))
            elif isinstance(event, (MatchFinishedEvent, MatchAbortedEvent)):
                for e in deferred:
                    await handle.queue.put(e)
                lifecycle = "finished" if isinstance(event, MatchFinishedEvent) else "aborted"
                result = _event_to_dict(event)
                result["lifecycle"] = lifecycle
                return _ok_result(result)
            else:
                deferred.append(event)
    except Exception as exc:
        return _error_result("internal_error", str(exc))


async def _get_history(
    registry: SessionRegistry,
    args: dict[str, Any],
) -> types.CallToolResult:
    match_id = args.get("match_id")
    seat = args.get("seat")

    if not isinstance(match_id, str):
        return _error_result("invalid_args", "match_id must be a string")
    if not isinstance(seat, int):
        return _error_result("invalid_args", "seat must be an integer")

    # Handle may be purged after finish — we can return from a cached copy,
    # but the registry purges on finish. Try registry first; fall through with empty.
    try:
        handle = registry.get(match_id, seat)
        history = [_event_to_dict(e) for e in handle.history]
    except KeyError:
        history = []

    return _ok_result(history)


async def _match_status(
    registry: SessionRegistry,
    args: dict[str, Any],
) -> types.CallToolResult:
    match_id = args.get("match_id")
    seat = args.get("seat")

    if not isinstance(match_id, str):
        return _error_result("invalid_args", "match_id must be a string")
    if not isinstance(seat, int):
        return _error_result("invalid_args", "seat must be an integer")

    try:
        handle = registry.get(match_id, seat)
        return _ok_result(handle.to_status_dict())
    except KeyError:
        return _ok_result({"lifecycle": "connecting"})


# ------------------------------------------------------------------ #
# Transport entrypoints
# ------------------------------------------------------------------ #


def run_stdio(registry: SessionRegistry | None = None) -> None:
    """Run the MCP server over stdio (for Claude Desktop)."""
    import anyio
    from mcp.server.stdio import stdio_server

    server = build_server(registry)

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    anyio.run(_run)


def run_http(
    host: str = "127.0.0.1",
    port: int = 9000,
    registry: SessionRegistry | None = None,
) -> None:
    """Run the MCP server over HTTP/SSE (for remote MCP clients)."""
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    server = build_server(registry)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Any) -> Any:
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    starlette_app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    uvicorn.run(starlette_app, host=host, port=port)
