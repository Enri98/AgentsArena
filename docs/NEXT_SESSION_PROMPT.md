# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md` and `IMPLEMENTATION_PLAN.md` strictly. Use the same workflow as the prior session: inspect the current baseline, make a concrete sequential plan, delegate bounded coding slices to cheaper subagents where available, review their diffs for correctness/conflicts, then run verification yourself before moving on.
>
> Current status: Connect 4 and Tic-Tac-Toe are complete built-in deterministic perfect-information games. The default registry resolves both. The pure local match layer supports immutable match execution, JSON-safe transcript dump/load, deterministic transcript validation, and in-process observation-based policies. README-backed examples now cover raw simulation, local match history, transcript validation, and deterministic policy auto-play. Phase 17 added `docs/ADAPTER_BOUNDARIES.md` plus import-boundary tests. Phase 18 added a pure serialized in-process adapter payload contract under `arena.adapters.in_process`. Phase 19 added `TypedPayloadPolicyAdapter` so typed local agents can use the payload contract without a second runner. No networking, persistence, subprocesses, timeouts, auth, matchmaking, or UI has been added.
>
> Verify with:
> `Set-ExecutionPolicy -Scope Process Bypass -Force; .\.venv\Scripts\Activate.ps1; ruff check .`
> `Set-ExecutionPolicy -Scope Process Bypass -Force; .\.venv\Scripts\Activate.ps1; pytest -q`
>
> Boundaries: keep `arena.core` and `arena.games` pure. Do not add remote agents, APIs, persistence, timeouts, UI concerns, auth, matchmaking, or orchestration code unless a new plan section explicitly justifies it.
>
> Recommended next branch: decide the next explicit plan section after Phase 19. Prefer README-backed adapter usage examples or another small pure deterministic game. Do not add FastAPI, WebSockets, persistence, subprocesses, timeouts, auth, matchmaking, or UI payloads without a new plan section and tests.
