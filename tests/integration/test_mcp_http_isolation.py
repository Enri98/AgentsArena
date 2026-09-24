"""MCP over HTTP/SSE isolates its clients (pre-Phase 40 leak review).

One SessionRegistry used to serve every SSE connection, so a client could read,
consume, or play any (match_id, seat) another client had joined. Two competing
agents on one MCP server could read each other's Liar's Dice hands.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client

from arena.mcp.server import build_http_app
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration.conftest import serve


async def _call(session: ClientSession, name: str, args: dict[str, Any]) -> Any:
    result = await session.call_tool(name, args)
    return json.loads(result.content[0].text)


def test_one_mcp_client_cannot_see_another_clients_seat() -> None:
    arena_app = create_app(rate_limiter=RateLimiter.unlimited())

    async def run(arena: Any, mcp: Any) -> dict[str, Any]:
        match = httpx.post(
            f"{arena.http_base_url}/matches",
            json={"game_id": "liarsdice", "per_turn_deadline_ms": 20_000},
        ).json()
        match_id = match["match_id"]
        url = f"{mcp.http_base_url}/sse"
        async with sse_client(url) as (ra, wa), sse_client(url) as (rb, wb):
            async with ClientSession(ra, wa) as a, ClientSession(rb, wb) as b:
                await a.initialize()
                await b.initialize()
                await _call(a, "join_match", {"server_url": match["seat_0_url"], "seat": 0})
                await _call(b, "join_match", {"server_url": match["seat_1_url"], "seat": 1})
                await asyncio.sleep(0.5)
                return {
                    "b_history_of_0": await _call(
                        b, "get_history", {"match_id": match_id, "seat": 0}
                    ),
                    "b_observation_of_0": await _call(
                        b, "get_observation", {"match_id": match_id, "seat": 0, "timeout": 1}
                    ),
                    "b_status_of_0": await _call(
                        b, "match_status", {"match_id": match_id, "seat": 0}
                    ),
                    "a_observation_of_0": await _call(
                        a, "get_observation", {"match_id": match_id, "seat": 0, "timeout": 5}
                    ),
                }

    with serve(arena_app) as arena, serve(build_http_app()) as mcp:
        out = asyncio.run(asyncio.wait_for(run(arena, mcp), timeout=60))

    assert out["b_history_of_0"] == []
    assert "observation_request" not in json.dumps(out["b_observation_of_0"])
    assert out["b_status_of_0"] == {"lifecycle": "connecting"}
    # The client that joined seat 0 still sees its own hand.
    own = out["a_observation_of_0"]["observation_request"]["observation"]
    assert own["my_dice"]
