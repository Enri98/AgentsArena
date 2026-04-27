# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md` and `IMPLEMENTATION_PLAN.md` strictly. Use the same workflow as the prior session: inspect the current baseline, make a concrete sequential plan, delegate bounded coding slices to cheaper subagents where available, review their diffs for correctness/conflicts, then run verification yourself before moving on.
>
> Current status: Connect 4 and Tic-Tac-Toe are complete built-in deterministic perfect-information games. The default registry resolves both. The pure local match layer supports immutable match execution, JSON-safe transcript dump/load, deterministic transcript validation, and in-process observation-based policies. The Tic-Tac-Toe docs/integration/handoff slice is complete.
>
> Verify with:
> `Set-ExecutionPolicy -Scope Process Bypass -Force; .\.venv\Scripts\Activate.ps1; ruff check .`
> `Set-ExecutionPolicy -Scope Process Bypass -Force; .\.venv\Scripts\Activate.ps1; pytest -q`
>
> Boundaries: keep `arena.core` and `arena.games` pure. Do not add remote agents, APIs, persistence, timeouts, UI concerns, auth, matchmaking, or orchestration code unless a new plan section explicitly justifies it.
>
> Recommended next branch: decide at the Phase 14/15 checkpoint whether to add another small game, improve docs/examples, or begin designing adapter boundaries. If implementing code, expand only the next plan slice, add tests immediately, and update `IMPLEMENTATION_PLAN.md`.
