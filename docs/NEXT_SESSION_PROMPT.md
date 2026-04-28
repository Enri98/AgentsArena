# Next Session Prompt

Paste this into a fresh Claude or Codex session:

> Continue work in `C:\Users\Enrico\Desktop\AgentsArena`. Follow `AGENTS.md` and `IMPLEMENTATION_PLAN.md` strictly. Use the same workflow as the prior session: inspect the current baseline, make a concrete sequential plan, delegate bounded coding slices to cheaper subagents where available, review their diffs for correctness/conflicts, then run verification yourself before moving on.
>
> Current status: Connect 4 and Tic-Tac-Toe are complete built-in deterministic perfect-information games. The default registry resolves both. The simulation layer is complete enough for the current deterministic perfect-information scope. The pure local match layer supports immutable match execution, JSON-safe transcript dump/load, deterministic transcript validation, and in-process observation-based policies. `arena.adapters.in_process` provides a serialized payload contract and `TypedPayloadPolicyAdapter` for typed local agents. `arena.runtime` provides pure in-memory arena/session coordination with match ids, player records, lifecycle states, runtime events, abort metadata (including `USER_QUIT` and `USER_INTERRUPT` reason codes), local session start/step/run, wrapped runtime transcripts, and UI-ready session status payloads. `arena.ui` provides a pure adapter over runtime payloads producing deterministic screen-level status and transcript payloads. `arena.cli` provides a terminal replay viewer (`python -m arena.cli`), per-game board renderers and input parsers (Connect 4, Tic-Tac-Toe), a file-based loader with frame stepping, an interactive driver (`arena.cli.play.play_match`), and a `python -m arena.cli.play` entrypoint for live human-vs-scripted play. `HumanPolicy` reads from an injected stdin stream and raises `HumanQuit` (a `BaseException` subclass) on `q`/`quit`/EOF/Ctrl-C; the driver converts this to a runtime abort with stable reason codes. Phase 25 is complete. No networking, subprocesses, timeouts, auth, matchmaking, or remote-agent protocols have been added.
>
> Verify with:
> `.\.venv\Scripts\ruff.exe check .`
> `.\.venv\Scripts\pytest.exe -q`
>
> Boundaries: keep `arena.core`, `arena.games`, `arena.match`, `arena.runtime`, and `arena.ui` free of rendering logic. `arena.cli` is the top-level consumer and must not be imported by any lower layer. Treat the next session as Phase 26: LLM-backed agent via the Anthropic SDK.
>
> Recommended next branch: use `docs/MATCH_ARENA_HANDOFF.md` and Phase 26 in `IMPLEMENTATION_PLAN.md`. Build a concrete `AnthropicAgent` in a new `arena.agents` package that implements `InProcessAgent[ObservationT, ActionT]` and is wrapped by the existing `TypedPayloadPolicyAdapter`. Extend `arena.cli.play.__main__` to accept `llm` as a seat spec. The user will need `ANTHROPIC_API_KEY` set; the Max plan does not cover programmatic API access.
