"""Per-recipient broadcast (Phase 38) and the spectator watermark.

Each distinct view is built once. A spectator whose welcome already carried a
turn is not sent it again — adversarial review of Phase 37 found that a spectator
attaching mid-broadcast could receive turns twice.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from arena.server.runtime_bridge import (
    MatchConnections,
    SeatConnection,
    SpectatorConnection,
    _broadcast_per_viewer,
)


class _Socket:
    async def send_text(self, text: str) -> None:  # pragma: no cover - never awaited
        raise AssertionError("broadcast must queue, not write inline")

    async def close(self, **_: object) -> None:
        return None


def _with_writer(conn):
    conn.writer_task = SimpleNamespace(cancel=lambda: None)  # a stand-in "running writer"
    return conn


def _drain(conn) -> list[dict]:
    frames = []
    while not conn.outbox.empty():
        frames.append(json.loads(conn.outbox.get_nowait()))
    return frames


def test_each_view_is_built_once_and_delivered_to_its_viewers() -> None:
    async def run():
        seat0 = _with_writer(SeatConnection(websocket=_Socket(), seat=0))
        seat1 = _with_writer(SeatConnection(websocket=_Socket(), seat=1))
        spec_a = _with_writer(SpectatorConnection(websocket=_Socket()))
        spec_b = _with_writer(SpectatorConnection(websocket=_Socket()))
        conns = MatchConnections(seat0, seat1)
        conns.add_spectator(spec_a)
        conns.add_spectator(spec_b)

        built: list[object] = []

        def build(viewer):
            built.append(viewer)
            return SimpleNamespace(model_dump=lambda mode: {"viewer": viewer})

        import arena.server.runtime_bridge as bridge

        original = bridge.dumps
        bridge.dumps = lambda env: json.dumps(env.model_dump(mode="json"))
        try:
            await _broadcast_per_viewer(conns, build)
        finally:
            bridge.dumps = original
        return built, [_drain(c) for c in (seat0, seat1, spec_a, spec_b)]

    built, frames = asyncio.run(run())
    assert sorted(built, key=str) == sorted([0, 1, None], key=str)
    assert frames == [[{"viewer": 0}], [{"viewer": 1}], [{"viewer": None}], [{"viewer": None}]]


def test_a_spectator_is_not_resent_turns_its_welcome_carried() -> None:
    async def run():
        seat0 = _with_writer(SeatConnection(websocket=_Socket(), seat=0))
        seat1 = _with_writer(SeatConnection(websocket=_Socket(), seat=1))
        spectator = _with_writer(SpectatorConnection(websocket=_Socket()))
        spectator.next_turn_index = 2  # its welcome carried turns 0 and 1
        conns = MatchConnections(seat0, seat1)
        conns.add_spectator(spectator)

        import arena.server.runtime_bridge as bridge

        original = bridge.dumps
        bridge.dumps = lambda env: json.dumps(env.model_dump(mode="json"))
        try:
            for index in range(4):
                await _broadcast_per_viewer(
                    conns,
                    lambda viewer, i=index: SimpleNamespace(
                        model_dump=lambda mode: {"turn_index": i}
                    ),
                    turn_index=index,
                )
        finally:
            bridge.dumps = original
        return _drain(seat0), _drain(spectator), spectator.next_turn_index

    seat_frames, spectator_frames, watermark = asyncio.run(run())
    assert [f["turn_index"] for f in seat_frames] == [0, 1, 2, 3]
    assert [f["turn_index"] for f in spectator_frames] == [2, 3]
    assert watermark == 4


def test_a_reconnected_seat_gets_its_own_writer() -> None:
    async def run():
        seat0 = _with_writer(SeatConnection(websocket=_Socket(), seat=0))
        seat1 = _with_writer(SeatConnection(websocket=_Socket(), seat=1))
        conns = MatchConnections(seat0, seat1)
        cancelled: list[bool] = []
        seat1.writer_task = SimpleNamespace(cancel=lambda: cancelled.append(True))
        fresh = SeatConnection(websocket=_Socket(), seat=1)
        conns.replace_seat(1, fresh)
        running = fresh.writer_task is not None
        fresh.writer_task.cancel()
        return running, cancelled

    running, cancelled = asyncio.run(run())
    assert running
    assert cancelled == [True], "the replaced seat's old writer must be stopped"
