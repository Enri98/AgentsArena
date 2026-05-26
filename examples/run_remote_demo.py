"""Run two Ollama-backed seats against a remote arena.server over WebSocket."""

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


def _create_match(http_base: str, game_id: str) -> dict[str, Any]:
    import httpx

    body = {"game_id": game_id, "players": [{"label": "seat-0"}, {"label": "seat-1"}]}
    resp = httpx.post(f"{http_base}/matches", json=body, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _resolve_definition(game_id: str) -> Any:
    from arena.games import build_default_registry

    try:
        return build_default_registry().get(game_id)
    except Exception as exc:
        raise ValueError(f"Unsupported game: {game_id!r}") from exc


def _dump_transcript(transcript: Any, path: Path) -> dict[str, Any]:
    """Serialise transcript to dict; handles both Pydantic models and plain dicts."""
    if hasattr(transcript, "model_dump"):
        data = transcript.model_dump(mode="json")
    else:
        data = dict(transcript)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


async def _run_happy(args: argparse.Namespace) -> int:
    from arena.agents.ollama._remote import run_remote_seat
    from arena.runtime import validate_runtime_transcript

    http_base = _ws_to_http(args.server_url)
    match_info = _create_match(http_base, args.game)
    seat_0_url: str = match_info["seat_0_url"]
    seat_1_url: str = match_info["seat_1_url"]

    print(f"Match created: {match_info['match_id']}")

    kw = dict(
        game_id=args.game,
        ollama_host=args.ollama_host,
        timeout=args.ollama_timeout,
        max_retries=args.ollama_max_retries,
        temperature=args.ollama_temperature,
    )

    results = await asyncio.gather(
        run_remote_seat(server_url=seat_0_url, seat=0, model=args.model_seat_0, **kw),
        run_remote_seat(server_url=seat_1_url, seat=1, model=args.model_seat_1, **kw),
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    definition = _resolve_definition(args.game)

    transcripts: list[dict[str, Any]] = []
    for i, (result_dict, transcript) in enumerate(results):
        path = out_dir / f"seat-{i}.transcript.json"
        data = _dump_transcript(transcript, path)
        transcripts.append(data)
        validated = validate_runtime_transcript(definition, data)
        print(f"seat-{i}: transcript valid (turns={len(validated.turns) if validated else 0})")

    for i, data in enumerate(transcripts):
        lc = data.get("lifecycle")
        if lc != "finished":
            print(f"ERROR: seat-{i} lifecycle={lc!r}, expected 'finished'", file=sys.stderr)
            return 1

    mt0 = transcripts[0].get("match_transcript")
    mt1 = transcripts[1].get("match_transcript")
    if mt0 != mt1:
        print("ERROR: match transcripts differ between seats", file=sys.stderr)
        return 1

    # Print report using format_runtime_session_report if available.
    # It needs a status payload; we don't have one here, so print a short summary.
    t0 = transcripts[0]
    print(
        f"\nMatch complete — lifecycle={t0['lifecycle']}, "
        f"turns={len((t0.get('match_transcript') or {}).get('turns', []))}"
    )
    if t0.get("abort") is None and (t0.get("match_transcript") or {}).get("result"):
        print(f"Result: {t0['match_transcript']['result']}")

    return 0


async def _run_abort(args: argparse.Namespace) -> int:
    """Abort scenario: seat 1 disconnects after N turns; verify peer_disconnected."""
    from arena.agents.ollama._adapters import OLLAMA_GAME_ADAPTERS
    from arena.agents.ollama._remote import run_remote_seat
    from arena.agents.ollama.agent import OllamaAgent
    from arena.agents.ollama.client import OllamaClient
    from arena.cli.remote import make_typed_agent_choose, run_remote_seat_async
    from arena.runtime import validate_runtime_transcript
    from arena.sdk.errors import MatchAbortedError

    http_base = _ws_to_http(args.server_url)
    match_info = _create_match(http_base, args.game)
    seat_0_url: str = match_info["seat_0_url"]
    seat_1_url: str = match_info["seat_1_url"]
    print(f"Match created (abort test): {match_info['match_id']}")

    definition = _resolve_definition(args.game)
    n_turns = args.abort_after_turns

    # Build a counting choose wrapper for seat 1.
    http_client = OllamaClient(host=args.ollama_host, timeout=args.ollama_timeout)
    agent1 = OllamaAgent(
        client=http_client,
        model=args.model_seat_1,
        prompt_builder=OLLAMA_GAME_ADAPTERS[args.game].prompt_builder_factory(),
        max_retries=args.ollama_max_retries,
        seed=0,
        temperature=args.ollama_temperature,
    )
    base_choose1 = make_typed_agent_choose(agent1, definition)
    call_count = [0]

    def counting_choose(req: Any) -> Any:
        call_count[0] += 1
        if call_count[0] > n_turns:
            raise RuntimeError(f"Aborting seat 1 after {n_turns} turns (demo)")
        return base_choose1(req)

    task0 = asyncio.create_task(
        run_remote_seat(
            server_url=seat_0_url,
            seat=0,
            model=args.model_seat_0,
            game_id=args.game,
            ollama_host=args.ollama_host,
            timeout=args.ollama_timeout,
            max_retries=args.ollama_max_retries,
            temperature=args.ollama_temperature,
        )
    )
    task1 = asyncio.create_task(
        run_remote_seat_async(seat_1_url, 1, counting_choose)
    )

    abort_transcript: Any = None
    results: dict[int, Any] = {}

    for coro in asyncio.as_completed([task0, task1]):
        try:
            result = await coro
            # Identify which task finished by checking which is done.
            for seat_idx, task in enumerate([task0, task1]):
                if task.done() and seat_idx not in results:
                    results[seat_idx] = result
        except MatchAbortedError as exc:
            abort_transcript = exc.transcript
            print(f"MatchAbortedError caught (expected): {exc}")
        except Exception as exc:
            # Seat 1 raises RuntimeError on forced abort; seat 0 may get MatchAbortedError.
            print(f"Seat raised: {type(exc).__name__}: {exc}")
            if abort_transcript is None and hasattr(exc, "transcript"):
                abort_transcript = exc.transcript

    if abort_transcript is None:
        print("ERROR: no abort transcript captured", file=sys.stderr)
        return 1

    if hasattr(abort_transcript, "model_dump"):
        abort_data = abort_transcript.model_dump(mode="json")
    else:
        abort_data = dict(abort_transcript)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "abort.transcript.json").write_text(
        json.dumps(abort_data, indent=2), encoding="utf-8"
    )

    lc = abort_data.get("lifecycle")
    if lc != "aborted":
        print(f"ERROR: expected lifecycle='aborted', got {lc!r}", file=sys.stderr)
        return 1

    abort_meta = abort_data.get("abort") or {}
    reason = abort_meta.get("reason", "")
    if reason != "peer_disconnected":
        print(
            f"ERROR: expected reason='peer_disconnected', got {reason!r}",
            file=sys.stderr,
        )
        return 1

    validate_runtime_transcript(definition, abort_data)
    print(f"Abort transcript valid — lifecycle=aborted, reason={reason}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Demo: two Ollama agents play a game on a remote arena.server."
    )
    parser.add_argument("--server-url", required=True, help="WebSocket base URL, e.g. ws://127.0.0.1:8080")
    parser.add_argument("--game", required=True, choices=["connect4", "tictactoe", "nim"])
    parser.add_argument("--model-seat-0", default="llama3.2")
    parser.add_argument("--model-seat-1", default="llama3.2")
    parser.add_argument("--out-dir", default="./runs/remote")
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-timeout", type=float, default=300.0)
    parser.add_argument("--ollama-max-retries", type=int, default=3)
    parser.add_argument("--ollama-temperature", type=float, default=0.0)
    parser.add_argument("--abort-after-turns", type=int, default=None)
    parser.add_argument("--skip-probe", action="store_true")
    args = parser.parse_args(argv)

    if not args.skip_probe:
        from arena.agents.ollama import OllamaClient
        from arena.agents.ollama.probe import probe_models

        models = list({args.model_seat_0, args.model_seat_1})
        print(f"Probing Ollama at {args.ollama_host} for models: {models}")
        probe_models(args.ollama_host, models, client=OllamaClient(args.ollama_host))
        print("Ollama probe OK.")

    if args.abort_after_turns is not None:
        return asyncio.run(_run_abort(args))
    return asyncio.run(_run_happy(args))


if __name__ == "__main__":
    sys.exit(main())
