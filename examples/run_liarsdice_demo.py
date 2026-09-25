"""Two Ollama agents play Liar's Dice on a remote arena.server, with a spectator.

The hidden-information counterpart of ``run_remote_demo.py``. Each seat's final
transcript is its own view (``view: "seat"``). It cannot be replayed, since it
lacks the other hand, and the two seats' transcripts differ by design. So
instead of replaying, the demo audits what every client received:

* no seat's transcript shows the other seat's hand, except inside a showdown;
* the spectator's stream never shows any hand mid-round, but does show the bids
  and every reveal.

Usage::

    python -m arena.server --port 8080          # in one terminal
    python examples/run_liarsdice_demo.py --server-url ws://127.0.0.1:8080 \\
        --model-seat-0 llama3.2 --model-seat-1 qwen2.5:1.5b
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


def _ws_to_http(ws_url: str) -> str:
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://"):]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://"):]
    return ws_url


def _create_match(http_base: str, dice: int, faces: int, deadline_ms: int) -> dict[str, Any]:
    import httpx

    body = {
        "game_id": "liarsdice",
        "game_config": {"dice_per_seat": dice, "faces": faces},
        "players": [{"label": "seat-0"}, {"label": "seat-1"}],
        # Local models can take a while, especially when two different models
        # take turns on one Ollama and each move reloads one.
        "per_turn_deadline_ms": deadline_ms,
        # Fail at creation, not at hello, if this server cannot serve hidden info.
        "supported_schema_versions": [4],
    }
    resp = httpx.post(f"{http_base}/matches", json=body, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


async def _spectate(url: str) -> list[dict[str, Any]]:
    import websockets

    frames: list[dict[str, Any]] = []
    async with websockets.connect(url, ping_interval=None) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "spectator_hello",
                    "schema_version": 4,
                    "payload": {
                        "client_name": "liarsdice-demo",
                        "client_version": "0.1.0",
                        "supported_schema_versions": [4],
                    },
                }
            )
        )
        try:
            async for raw in ws:
                frames.append(json.loads(raw))
        except websockets.exceptions.ConnectionClosed:
            pass
    return frames


async def _run(args: argparse.Namespace) -> int:
    from arena.agents.ollama._remote import run_remote_seat
    from arena.games.liarsdice.audit import leaked_hand_paths

    http_base = _ws_to_http(args.server_url)
    match = _create_match(http_base, args.dice, args.faces, args.turn_deadline_ms)
    print(f"Match created: {match['match_id']}")

    spectate_url = f"{args.server_url.rstrip('/')}/matches/{match['match_id']}/spectate"
    spectator = asyncio.create_task(_spectate(spectate_url))
    await asyncio.sleep(0.2)  # let the spectator attach before play starts

    kw = dict(
        game_id="liarsdice",
        ollama_host=args.ollama_host,
        timeout=args.ollama_timeout,
        max_retries=args.ollama_max_retries,
        temperature=args.ollama_temperature,
    )
    results = await asyncio.gather(
        run_remote_seat(server_url=match["seat_0_url"], seat=0, model=args.model_seat_0, **kw),
        run_remote_seat(server_url=match["seat_1_url"], seat=1, model=args.model_seat_1, **kw),
    )
    spectator_frames = await asyncio.wait_for(spectator, timeout=30)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = True

    for seat, (_, transcript) in enumerate(results):
        data = transcript.model_dump(mode="json")
        (out_dir / f"seat-{seat}.transcript.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        leaks = leaked_hand_paths(data, seat)
        view = (data.get("view"), data.get("viewer_seat"))
        print(f"seat-{seat}: lifecycle={data['lifecycle']} view={view} leaks={len(leaks)}")
        ok &= data["lifecycle"] == "finished" and view == ("seat", seat) and not leaks
        for path in leaks[:5]:
            print(f"  LEAK {path}", file=sys.stderr)

    (out_dir / "spectator.frames.json").write_text(
        json.dumps(spectator_frames, indent=2), encoding="utf-8"
    )
    spectator_leaks = [p for frame in spectator_frames for p in leaked_hand_paths(frame, None)]
    events = [
        e
        for frame in spectator_frames
        if frame.get("type") == "turn_committed"
        for e in frame["payload"]["events"]
    ]
    reveals = [e for e in events if e["event_type"] == "BidCalled"]
    bids = [e for e in events if e["event_type"] == "BidMade"]
    print(
        f"spectator: frames={len(spectator_frames)} bids={len(bids)} "
        f"reveals={len(reveals)} leaks={len(spectator_leaks)}"
    )
    ok &= not spectator_leaks and bool(reveals)

    for n, reveal in enumerate(reveals, start=1):
        p = reveal["payload"]
        print(
            f"  round {n}: seat {p['seat']} called {p['quantity']} x {p['face']}; "
            f"hands {p['dice'][0]} / {p['dice'][1]} had {p['count']}; "
            f"seat {p['loser']} lost a die"
        )
    won = [e for e in events if e["event_type"] == "LiarsDiceMatchWon"]
    if won:
        print(f"Winner: seat {won[0]['payload']['winner_seat']}")

    print("OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--model-seat-0", default="llama3.2")
    parser.add_argument("--model-seat-1", default="llama3.2")
    parser.add_argument("--dice", type=int, default=3)
    parser.add_argument("--faces", type=int, default=6)
    parser.add_argument("--out-dir", default="./runs/liarsdice")
    parser.add_argument("--turn-deadline-ms", type=int, default=300_000)
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-timeout", type=float, default=300.0)
    parser.add_argument("--ollama-max-retries", type=int, default=3)
    # Above zero so a retry after an illegal move is not the same answer again.
    parser.add_argument("--ollama-temperature", type=float, default=0.5)
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
