# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md` and `IMPLEMENTATION_PLAN.md` strictly. Use the same workflow as the prior session: inspect the current baseline, make a concrete sequential plan, delegate bounded coding slices to cheaper subagents where available, review their diffs for correctness/conflicts, then run verification yourself before moving on.
>
> Current status: Connect 4 and Tic-Tac-Toe are complete built-in deterministic perfect-information games. The default registry resolves both. The simulation layer is complete enough for the current deterministic perfect-information scope. The pure local match layer supports immutable match execution, JSON-safe transcript dump/load, deterministic transcript validation, and in-process observation-based policies. `arena.adapters.in_process` provides a serialized payload contract and `TypedPayloadPolicyAdapter` for typed local agents. `arena.runtime` provides pure in-memory arena/session coordination with match ids, player records, lifecycle states, runtime events, abort metadata, local session start/step/run, wrapped runtime transcripts, and UI-ready session status payloads. `arena.ui` provides a pure adapter over runtime payloads producing deterministic screen-level status and transcript payloads. `arena.cli` provides a terminal replay viewer (`python -m arena.cli`) plus per-game board renderers (Connect 4, Tic-Tac-Toe), a file-based loader with frame stepping, and an end-to-end example script in `examples/run_and_render_match.py`. Phase 24 is complete. No networking, persistence beyond JSON files, subprocesses, timeouts, auth, matchmaking, live human play, or remote-agent protocols have been added.
>
> Verify with:
> `.\.venv\Scripts\ruff.exe check .`
> `.\.venv\Scripts\pytest.exe -q`
>
> Boundaries: keep `arena.core`, `arena.games`, `arena.match`, `arena.runtime`, and `arena.ui` free of rendering logic. `arena.cli` is the top-level consumer and must not be imported by any lower layer. Treat the next session as Phase 25: live human play via `HumanPolicy`. A `HumanPolicy` needs an injected input-reader so tests can provide scripted input without touching stdin. It breaks determinism for the human seat; golden tests should target only the scripted seat. No networking or transport adapters should be added in Phase 25.
>
> Recommended next branch: use `docs/MATCH_ARENA_HANDOFF.md` and Phase 25 in `IMPLEMENTATION_PLAN.md`. Design the `HumanPolicy` interface with an injectable `read_action` callback, wire it into `Arena.run_session(...)` or a dedicated helper, and add focused tests using a scripted callback sequence. Keep the rest of the stack unchanged.
