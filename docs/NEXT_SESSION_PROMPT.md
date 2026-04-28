# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md` and `IMPLEMENTATION_PLAN.md` strictly. Use the same workflow as the prior session: inspect the current baseline, make a concrete sequential plan, delegate bounded coding slices to cheaper subagents where available, review their diffs for correctness/conflicts, then run verification yourself before moving on.
>
> Current status: Connect 4 and Tic-Tac-Toe are complete built-in deterministic perfect-information games. The default registry resolves both. The simulation layer is complete enough for the current deterministic perfect-information scope. The pure local match layer supports immutable match execution, JSON-safe transcript dump/load, deterministic transcript validation, and in-process observation-based policies. `arena.adapters.in_process` provides a serialized payload contract and `TypedPayloadPolicyAdapter` for typed local agents. `arena.runtime` provides pure in-memory arena/session coordination with match ids, player records, lifecycle states, runtime events, abort metadata, local session start/step/run, wrapped runtime transcripts, and UI-ready session status payloads. No networking, persistence, subprocesses, timeouts, auth, matchmaking, concrete UI rendering, or remote-agent protocols have been added.
>
> Verify with:
> `.\.venv\Scripts\ruff.exe check .`
> `.\.venv\Scripts\pytest.exe -q`
>
> Boundaries: keep `arena.core`, `arena.games`, and `arena.match` pure. Treat the next session as Phase 21: runtime / UI contract stabilization. The UI may consume stable JSON-safe runtime payloads, but rendering logic, component state, transport, persistence, auth, matchmaking, subprocesses, timeouts, and remote agents remain out of scope unless a new plan section explicitly justifies them.
>
> Recommended next branch: use `docs/MATCH_ARENA_HANDOFF.md` and Phase 21 in `IMPLEMENTATION_PLAN.md`. Start by deciding the exact UI-facing runtime payload fields, whether `latest_snapshot` is sufficient for board rendering, whether runtime status should include recent events, and how to test payload shape stability before adding any UI code.
