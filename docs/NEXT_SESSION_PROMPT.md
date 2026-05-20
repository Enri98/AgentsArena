# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md`, `IMPLEMENTATION_PLAN.md`, and `docs/NETWORK_PROTOCOL.md` strictly. Use the same workflow as prior sessions: inspect the current baseline, expand only the current slice, delegate bounded coding slices to cheaper subagents where available, review their diffs, then run verification yourself before moving on.
>
> Current status: **Phases 0 - 35 are complete. The v1 milestone is reached.** The simulation core, local match runner, runtime coordinator, UI adapter, terminal CLI, local Ollama agents, WebSocket adapter, server with `MatchRegistry`, reference Python SDK, Ollama-over-WS, resilience (per-turn deadlines, heartbeats, reconnect with resume tokens), structured logging, public deployment story (Dockerfile, `fly.toml`, `docs/DEPLOYMENT.md`), the remote acceptance demo (`examples/run_remote_demo.py`), and the optional MCP server layer (`arena.mcp`, stdio + HTTP/SSE) all ship and pass `ruff` + `pytest`.
>
> Side note: a Nim game (`src/arena/games/nim/`) was added in commit `3da879a` outside the documented roadmap. It is registered in `build_default_registry()`, has a `NimPromptBuilder`, ships with action schemas in `arena.mcp.schemas`, and is exercised by the remote demo and integration tests.
>
> What's next is open. Defensible directions:
> - **Public-server smoke test**: walk through `docs/DEPLOYMENT.md` for real — `flyctl launch` / `flyctl deploy` — and run `examples/run_remote_demo.py --server-url wss://<your-app>.fly.dev --game connect4 --abort-after-turns 3`. Verify both happy and abort transcripts in the wild.
> - **MCP transport e2e test** (deferred from Phase 35): spawn `python -m arena.mcp --stdio` as a subprocess, drive a Connect 4 match through the official `mcp` SDK's stub client.
> - **v2 candidates** (NOT yet in scope): TypeScript SDK port, web spectator UI, transcript persistence beyond JSON files, real auth, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, Anthropic-SDK-backed agent.
> - **Nim cleanup**: backfill `arena.cli.play.__main__` to accept `--game nim` (currently only `connect4`/`tictactoe`). The new `run_remote_seat` helper already supports Nim end-to-end; only the local CLI driver lags.
>
> Verify with:
> `.\.venv\Scripts\ruff.exe check .`
> `.\.venv\Scripts\pytest.exe -q`
>
> Boundaries (full list in `CLAUDE.md` and `AGENTS.md`): `arena.core`, `arena.games`, `arena.match`, `arena.adapters.*`, `arena.runtime`, `arena.ui`, `arena.cli`, `arena.sdk`, `arena.agents.*`, and `arena.mcp` must not enforce wall-clock deadlines or instantiate loggers at module-load scope. Per-turn deadlines and structured logging are exclusive to `arena.server`. Architecture boundary tests enforce import direction: `arena.mcp` may only import `arena.sdk` and `arena.core`. The `arena.agents` → `arena.sdk` boundary is still forbidden by `test_sdk_boundaries.py`; the Ollama remote helper reaches the SDK transitively through `arena.cli.remote` (which is permitted to import `arena.sdk`).
>
> v1 acceptance demo (Phase 34): two local Ollama agents on the user's laptop both connect to a publicly reachable `arena.server`, complete one clean Connect 4 match, and complete one deliberate-abort scenario. This is reproducible per `docs/DEPLOYMENT.md`. v2 deferrals: persistence beyond JSON files, real auth, web spectator UI, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, TypeScript SDK port, Anthropic-SDK-backed agent.
