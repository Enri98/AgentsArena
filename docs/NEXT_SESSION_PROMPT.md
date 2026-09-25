# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `CLAUDE.md`, `AGENTS.md`,
> `IMPLEMENTATION_PLAN.md` and `docs/NETWORK_PROTOCOL.md` strictly. Inspect the current baseline
> first, expand only the current slice, and verify everything yourself before moving on.
>
> **Status (2026-09-25): v1 (Phases 0-35) and the v2 roadmap (Phases 36-42) are complete.** The
> wire is at `schema_version` 4 (decoders accept 1-4). Six games ship: Connect 4, Tic-Tac-Toe,
> Nim, Pig (chance), Liar's Dice (hidden information and chance) and Rock-Paper-Scissors
> (simultaneous). The server has spectators, rate limits, per-viewer frames, resume, and public
> transcripts in memory, files or SQLite. There are Python and TypeScript (`sdk-ts/`) clients and
> an MCP server, and the scaffold generates working games of each kind. `docs/MATCH_ARENA_HANDOFF.md`
> has the current state and known gaps.
>
> **Owner rules.**
> - After each slice, dispatch adversarial reviewer subagents over it, and fix confirmed findings
>   before starting the next.
> - Commit often; push and merge once CI is green and the reviews are clean.
> - Never call paid APIs. Local Ollama (`qwen2.5:1.5b` at `http://127.0.0.1:11434`) is fine.
>
> **Run the real stack after server or SDK changes.** Start `python -m arena.server`, then run
> `examples/run_remote_demo.py --game rps` (local Ollama) and
> `node sdk-ts/examples/play_match.ts http://127.0.0.1:8080 pig last`. Every integration test uses a
> sansio test server, so tests cannot catch entry-point regressions. That is how Phase 38 found
> that `python -m arena.server` had been aborting every match.
>
> **Constraints that are easy to rediscover the hard way:**
> - A slow reader must never stall a match. Outbound queues are per connection.
> - A seed in config or state is public, because both are broadcast.
> - Everything sent to a viewer is built for that viewer.
> - One live WebSocket per Starlette `TestClient` test; two sockets belong in
>   `tests/integration/`.
>
> **Next work** (not numbered phases): the known gaps in the handoff. That means packaging
> metadata and a release workflow, and a type checker in CI (the `library-basics` branch). Then
> deploy for real (`fly.toml`, `ARENA_PUBLIC_URL`) and publish the Python and TypeScript packages.
>
> Verify with:
> `.\.venv\Scripts\ruff.exe check .`
> `.\.venv\Scripts\pytest.exe -q`
> `cd sdk-ts; npm ci; npm run typecheck; npm test`
>
> **Still deferred:** real auth, a designed web UI, lobby and matchmaking, Prometheus metrics,
> OpenTelemetry tracing, an Anthropic-SDK-backed agent, third-party game registration, and more
> than two seats.
