"""End-to-end MCP stdio transport test.

Spawns `python -m arena.mcp --stdio` as a real subprocess and drives it
through the official MCP client (JSON-RPC over stdio). This exercises the
full transport handshake — initialize, list_tools, call_tool — that the
in-process integration tests in test_mcp_integration.py deliberately skip.

This is the Phase 35 follow-up flagged in IMPLEMENTATION_PLAN.md.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.integration.conftest import RunningServer


def _create_match(http_base: str, game_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"game_id": game_id, **extra}
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _parse(result: Any) -> dict[str, Any] | list[Any]:
    """Pull the JSON payload out of an MCP CallToolResult."""
    assert result.content, f"empty tool result: {result}"
    text = result.content[0].text
    return json.loads(text)


def test_mcp_stdio_subprocess_drives_tictactoe(running_server: RunningServer) -> None:
    """Full MCP stdio handshake + tool calls drive a Tic-Tac-Toe match to completion."""

    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "arena.mcp", "--stdio"],
            env=None,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                # Transport-level handshake
                init_result = await session.initialize()
                assert init_result.serverInfo.name == "arena-mcp"

                # Sanity check that all 5 documented tools are advertised
                listed = await session.list_tools()
                tool_names = {t.name for t in listed.tools}
                assert tool_names == {
                    "join_match",
                    "get_observation",
                    "make_move",
                    "get_history",
                    "match_status",
                }

                # Create a match via the real arena.server
                match = _create_match(
                    running_server.http_base_url,
                    "tictactoe",
                    players=[{"label": "x"}, {"label": "o"}],
                )
                seat_0_url: str = match["seat_0_url"]
                seat_1_url: str = match["seat_1_url"]

                # Join both seats through the subprocess MCP server
                join0 = await session.call_tool(
                    "join_match", {"server_url": seat_0_url, "seat": 0}
                )
                join1 = await session.call_tool(
                    "join_match", {"server_url": seat_1_url, "seat": 1}
                )
                r0 = _parse(join0)
                r1 = _parse(join1)
                assert isinstance(r0, dict) and not r0.get("error"), r0
                assert isinstance(r1, dict) and not r1.get("error"), r1
                assert r0["match_id"] == r1["match_id"]
                match_id: str = r0["match_id"]
                assert r0["game_id"] == "tictactoe"

                # Drive the match to a terminal state
                finished = [False, False]
                for _ in range(30):
                    if all(finished):
                        break
                    for seat in (0, 1):
                        if finished[seat]:
                            continue
                        obs_res = await session.call_tool(
                            "get_observation",
                            {"match_id": match_id, "seat": seat, "timeout": 10.0},
                        )
                        obs_data = _parse(obs_res)
                        assert isinstance(obs_data, dict)
                        if obs_data.get("error"):
                            finished[seat] = True
                            continue
                        if obs_data.get("lifecycle") in ("finished", "aborted"):
                            finished[seat] = True
                            continue

                        obs_req = obs_data.get("observation_request", {})
                        obs = obs_req.get("observation", obs_data.get("observation", {}))
                        legal = obs.get("legal_actions", [])
                        if not legal:
                            finished[seat] = True
                            continue

                        action = {"row": legal[0]["row"], "column": legal[0]["column"]}
                        move_res = await session.call_tool(
                            "make_move",
                            {"match_id": match_id, "seat": seat, "action": action},
                        )
                        move_data = _parse(move_res)
                        assert isinstance(move_data, dict)
                        if move_data.get("lifecycle") in ("finished", "aborted"):
                            finished[seat] = True

                assert all(finished), "match did not reach a terminal state"

                # match_status should not blow up post-finish
                status_res = await session.call_tool(
                    "match_status", {"match_id": match_id, "seat": 0}
                )
                status_data = _parse(status_res)
                assert isinstance(status_data, dict)
                assert status_data.get("lifecycle") in (
                    "finished",
                    "connecting",
                ), status_data

                # get_history returns a list (possibly empty after registry purge)
                hist_res = await session.call_tool(
                    "get_history", {"match_id": match_id, "seat": 1}
                )
                hist_data = _parse(hist_res)
                assert isinstance(hist_data, list)

    asyncio.run(run())


def test_mcp_stdio_unknown_match_returns_error(running_server: RunningServer) -> None:
    """A call_tool against a bogus match_id returns a structured error, not a crash."""

    async def run() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "arena.mcp", "--stdio"],
            env=None,
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_observation",
                    {"match_id": "nonexistent", "seat": 0},
                )
                data = _parse(result)
                assert isinstance(data, dict)
                assert data.get("error") is True
                assert "code" in data

    asyncio.run(run())
