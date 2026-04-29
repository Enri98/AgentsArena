# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md`, `IMPLEMENTATION_PLAN.md`, and `docs/NETWORK_PROTOCOL.md` strictly. Use the same workflow as prior sessions: inspect the current baseline, expand only the current slice, delegate bounded coding slices to cheaper subagents where available, review their diffs, then run verification yourself before moving on.
>
> Current status: Phases 0 - 26 are complete. The simulation core, local match runner, runtime coordinator, UI adapter, terminal CLI (`python -m arena.cli` and `python -m arena.cli.play`), and local Ollama agents (`arena.agents.ollama`) all ship and run end-to-end on Connect 4 and Tic-Tac-Toe.
>
> Phase 27 (Network protocol design checkpoint) is complete: `docs/NETWORK_PROTOCOL.md` is now the language-agnostic source of truth for the wire protocol; `CLAUDE.md`, `AGENTS.md`, `docs/ADAPTER_BOUNDARIES.md`, and `docs/MATCH_ARENA_HANDOFF.md` reflect the new layer rules, the lifted bans on networking and per-turn deadlines (deadlines live exclusively in `arena.server`, never in `arena.runtime`), and the v2 deferrals.
>
> Next phase: **Phase 28 — `arena.adapters.websocket` payload contract**. Add a new sibling adapter to `arena.adapters.in_process` containing only Pydantic v2 envelope models per protocol message type, a discriminated-union message-type validator, and pure JSON encode/decode helpers. No I/O, no `websockets`/`aiohttp` imports, no server or client code. Reuse `arena.adapters.in_process.ObservationRequestPayload`, `ActionResponsePayload`, and `DomainErrorPayload` verbatim as the bodies of `observation_request`, `action_response`, and `action_rejected`. Add an architecture test forbidding `arena.core`, `arena.games`, `arena.match`, `arena.runtime`, and `arena.ui` from importing `arena.adapters.websocket`. The slice is described in `IMPLEMENTATION_PLAN.md` Phase 28.
>
> Verify with:
> `.\.venv\Scripts\ruff.exe check .`
> `.\.venv\Scripts\pytest.exe -q`
>
> Boundaries (full list in `CLAUDE.md` and `AGENTS.md`): `arena.core`, `arena.games`, `arena.match`, `arena.adapters.*`, `arena.runtime`, `arena.ui`, `arena.cli`, `arena.sdk`, and `arena.agents.*` must not enforce wall-clock deadlines or instantiate loggers at module-load scope. Per-turn deadlines and structured logging are exclusive to `arena.server` (Phase 29+). Architecture boundary tests enforce import direction.
>
> v1 acceptance demo (Phase 34): two local Ollama agents on the user's laptop both connect to a publicly reachable `arena.server`, complete one clean Connect 4 match, and complete one deliberate-abort scenario. v2 deferrals: persistence beyond JSON files, real auth, web spectator UI, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, TypeScript SDK port, Anthropic-SDK-backed agent.
