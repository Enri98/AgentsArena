# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md`, `IMPLEMENTATION_PLAN.md`, and `docs/NETWORK_PROTOCOL.md` strictly. Use the same workflow as prior sessions: inspect the current baseline, expand only the current slice, delegate bounded coding slices to cheaper subagents where available, review their diffs, then run verification yourself before moving on.
>
> **Current status (verified 2026-09-23): Phases 0-36 complete.** Phase 36 shipped CI, protocol §13 rate limits, match eviction, the public-view contract, the connection registry with per-connection outboxes, the live spectator channel, and a browser viewer — all on the v1 wire with no schema bump. 714 tests pass. **Next up: Phase 37, the chance-node primitive, which carries the bump to `schema_version=2`.**
>
> **Previous milestone: Phases 0-35, v1.** `main` is clean, `ruff` passes, `pytest -q` reports **675 passed**. The simulation core, local match runner, runtime coordinator, UI adapter, terminal CLI, local Ollama agents, WebSocket adapter, server with `MatchRegistry`, reference Python SDK, Ollama-over-WS, resilience (per-turn deadlines, heartbeats, reconnect with resume tokens), structured logging, deployment artifacts (`Dockerfile`, `fly.toml`, `docs/DEPLOYMENT.md`), the remote acceptance demo (`examples/run_remote_demo.py`), and the MCP server layer (`arena.mcp`, stdio + HTTP/SSE) all ship.
>
> **Post-v1 work already landed** (see the "Post-v1 work" section of `IMPLEMENTATION_PLAN.md`): a third game (`arena.games.nim`), per-layer adapter registries replacing per-game dispatch ladders, `docs/ADDING_A_GAME.md` plus the `python -m arena.games.scaffold` generator, and a draft RFC at `docs/RFC_IMPERFECT_INFORMATION.md`.
>
> **Known gaps — read before proposing work:**
> - `docs/NETWORK_PROTOCOL.md` §13 rate limits are **specified but not implemented**. Close code `4429` is emitted nowhere in `src/`. With no auth in v1, this blocks any public deployment.
> - No CI. There is no `.github/` workflow.
> - Nothing is deployed; `fly.toml` still says `app = "arena-server"`.
> - `agents-arena` is not on PyPI, so no third party can join a match without cloning the repo.
>
> **Next direction — v2 roadmap, Phases 36-42, approved 2026-09-22.** Specified in `IMPLEMENTATION_PLAN.md` under "v2 roadmap". Order: ~~36 spectator endpoint + transport refactor + §13 rate limits + CI~~ **COMPLETE 2026-09-23** → 37 chance-node primitive (**bump to `schema_version=2`**) → 38 imperfect-information contract (**bump to 3**) → 39 Liar's Dice → 40 transcript persistence + `GET /matches/{id}/public-transcript` → 41 generalized turn loop (**bump to 4**) → 42 docs + packaged TypeScript SDK. Expand only the current phase, one slice at a time.
>
> **The phase specs were revised on 2026-09-22 after an adversarial review that verified every claim against the code.** Each of Phases 36-38 opens with a note explaining what the first draft got wrong and why. Read those notes — they encode three constraints that are easy to rediscover the hard way: a slow spectator can stall `run_match` and abort a match; a game seed placed in config is broadcast to both seats and embedded in every snapshot; and §13 rate limits must land before the spectator endpoint opens.
>
> `docs/RFC_IMPERFECT_INFORMATION.md` is **superseded as a plan** and retained as analysis — §1-5 are still accurate, §6-8 are historical. Four owner decisions diverge from what that RFC recommends, so read the decision table in the plan rather than the RFC: a real chance-node primitive (not seeded init-time randomness), spectator first, transcript persistence in scope, and simultaneous moves in scope but deferred to Phase 41.
>
> **Adding a game:** follow `docs/ADDING_A_GAME.md`. A new game registers with each layer's adapter registry (`arena.cli.games`, `arena.mcp.games`, `arena.agents.ollama._adapters`) — do not add `if game_id == ...` dispatch branches.
>
> Verify with:
> `.\.venv\Scripts\ruff.exe check .`
> `.\.venv\Scripts\pytest.exe -q`
>
> **Boundaries** (full list in `CLAUDE.md` and `AGENTS.md`): `arena.core`, `arena.games`, `arena.match`, `arena.adapters.*`, `arena.runtime`, `arena.ui`, `arena.cli`, `arena.sdk`, `arena.agents.*`, and `arena.mcp` must not enforce wall-clock deadlines or instantiate loggers at module-load scope. Per-turn deadlines and structured logging are exclusive to `arena.server`. Architecture tests enforce import direction: `arena.mcp` may only import `arena.sdk` and `arena.core`. The `arena.agents` → `arena.sdk` boundary is still forbidden by `test_sdk_boundaries.py`; the Ollama remote helper reaches the SDK transitively through `arena.cli.remote` (which is permitted to import `arena.sdk`).
>
> **v2 deferrals:** persistence beyond JSON files, real auth, web spectator UI, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, TypeScript SDK port, Anthropic-SDK-backed agent, third-party game registration.
