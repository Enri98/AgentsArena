"""make_move must confirm the caller's own move (adversarial review, Phase 37).

Since chance nodes, one move can commit several turns — a Pig roll is followed by
the die result — and the opponent's turns sit on the same queue. make_move used
to return whichever turn_committed came first, often an old one.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from arena.adapters.websocket.messages import TurnCommittedBody
from arena.mcp.server import _make_move
from arena.sdk._events import TurnCommittedEvent


def _committed(turn_index: int, seat: int | None, kind: str = "action") -> TurnCommittedEvent:
    return TurnCommittedEvent(
        body=TurnCommittedBody(
            turn_record={"turn_index": turn_index, "seat": seat, "kind": kind},
            post_snapshot={},
            events=[],
        )
    )


class _Session:
    async def send_action(self, action, turn_id=None):  # noqa: ANN001
        return None


def test_make_move_returns_the_callers_own_turn() -> None:
    async def run() -> dict:
        queue: asyncio.Queue = asyncio.Queue()
        # Stale backlog: the opponent's move and a roll, then ours and its roll.
        for event in (
            _committed(0, 1),
            _committed(1, None, "chance"),
            _committed(2, 0),
            _committed(3, None, "chance"),
        ):
            queue.put_nowait(event)
        handle = SimpleNamespace(queue=queue, session=_Session())
        registry = SimpleNamespace(get=lambda match_id, seat: handle)
        result = await _make_move(
            registry, {"match_id": "m", "seat": 0, "action": {"choice": "roll"}}
        )
        return json.loads(result.content[0].text)

    confirmed = asyncio.run(run())
    assert confirmed["turn_record"]["turn_index"] == 2
    assert confirmed["turn_record"]["seat"] == 0
