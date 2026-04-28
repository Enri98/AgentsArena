# AgentsArena — Project Context

Python 3.11 library that will eventually power an agent-vs-agent arena. Current scope is a pure simulation + local runtime stack for sequential, deterministic, perfect-information games. No networking, persistence, subprocesses, timeouts, auth, matchmaking, remote agents, or UI rendering yet.

> Source of truth for plan + status: `IMPLEMENTATION_PLAN.md`. Working rules + style: `AGENTS.md`. Boundary contract for adapters: `docs/ADAPTER_BOUNDARIES.md`. Cross-session handoff: `docs/MATCH_ARENA_HANDOFF.md`.

> **Activate `.venv` before running any script.** Verify with `.\.venv\Scripts\ruff.exe check .` and `.\.venv\Scripts\pytest.exe -q`.

## Layered architecture (strict, downward-only deps)

| Layer | Package | Responsibility |
|-------|---------|---------------|
| Simulation core | `arena.core` | Types, seats, exceptions, events, actions, observations, results, config, `GameDefinition`, `RulesEngine`, `Serializer`, `Registry`. Pure, immutable, no I/O. |
| Games | `arena.games.connect4`, `arena.games.tictactoe` | Concrete game vertical slices (config, state, action, observation, events, rules, serializer, definition). Both registered via `build_default_registry()`. |
| Local match | `arena.match` | `LocalMatch`, `TurnRecord`, `start_match` / `apply_match_action`, transcript dump/load/validate, in-process `Policy` protocol, `run_local_match`. Per-match isolated rules engine copy. |
| Adapters | `arena.adapters.in_process` | Serialized payload contract: `ObservationRequestPayload`, `ActionResponsePayload`, domain-error payloads, `apply_payload_policy_turn`, `TypedPayloadPolicyAdapter` + `InProcessAgent` for typed local agents. |
| Runtime | `arena.runtime` | Pure in-memory `Arena` coordinator, `MatchSession`, opaque `MatchId`, `PlayerRecord`, lifecycle (`created`/`running`/`finished`/`aborted`), runtime events, abort metadata, runtime exceptions, JSON-safe `dump_session_status` / `dump_runtime_transcript` (both pinned `schema_version=1`), `format_runtime_session_report`. |
| UI adapter | `arena.ui` | Pure adapter over runtime payloads. `build_match_status`, `build_match_transcript`, `build_match_screen`. Reshapes envelopes into screen-level payloads, exposes `state_payload` from snapshots without recomputing rules. |

Dependency direction is enforced by architecture tests: `core`/`games` import none of the upper layers; `match` cannot import adapters/runtime/ui; adapters cannot import runtime/ui; runtime cannot import ui.

## Implementation status

Completed phases (per `IMPLEMENTATION_PLAN.md`): 0–10 simulation baseline, 11 local match, 12 transcripts, 13 in-process policy protocol, 14 checkpoint, 15 Tic-Tac-Toe, 16 README examples, 17 adapter boundary doc, 18 serialized in-process adapter, 19 typed payload adapter, 20 runtime baseline (Slices 1–4), 21 runtime/UI contract stabilization (Slice 1), 22 human-readable formatting helpers, 23 UI adapter boundary.

Most recent commits track Phase 23 (`arena.ui` adapter) and Phase 22 (formatting helpers) on top of the runtime payload contract. The plan's "post-baseline roadmap" continues with future UI/transport/persistence phases — none implemented.

## Core design rules (do not violate)

- Frozen dataclasses for in-memory domain state/actions; Pydantic v2 for config + boundary payloads + JSON Schema.
- Integer seat ids inside the simulation core. Player names/labels live in runtime/UI layers.
- Store only minimum authoritative state; derive legality, terminal, winners on demand.
- `apply_action(...)` revalidates legality defensively; raises typed domain exceptions (`WrongPlayer`, `IllegalAction`, `GameFinished`, `InvalidConfig`, ...).
- Serialize only at boundaries via dedicated `Serializer`; every accepted move yields a full post-move snapshot, and snapshots must rehydrate.
- Runtime aborts wrap non-result failures while preserving the original `ArenaCoreError` as cause.
- Runtime payload `schema_version` is fixed at `1`; any incompatible change must bump it explicitly.
- Architecture/import-boundary tests are load-bearing — do not introduce upward imports.

## Working workflow

1. Re-read the relevant section of `IMPLEMENTATION_PLAN.md` and only expand the current slice.
2. Implement the smallest coherent change; add/update focused unit tests near the code.
3. Run ruff + pytest from the venv.
4. Update the plan's slice status + handoff docs when a slice completes.
5. Do not skip ahead, do not refactor unrelated modules, do not introduce deferred infrastructure (transport, persistence, subprocesses, deadlines, auth, matchmaking, UI rendering, remote agents).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **AgentsArena** (1440 symbols, 4161 relationships, 89 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## When Debugging

1. `gitnexus_query({query: "<error or symptom>"})` — find execution flows related to the issue
2. `gitnexus_context({name: "<suspect function>"})` — see all callers, callees, and process participation
3. `READ gitnexus://repo/AgentsArena/process/{processName}` — trace the full execution flow step by step
4. For regressions: `gitnexus_detect_changes({scope: "compare", base_ref: "main"})` — see what your branch changed

## When Refactoring

- **Renaming**: MUST use `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` first. Review the preview — graph edits are safe, text_search edits need manual review. Then run with `dry_run: false`.
- **Extracting/Splitting**: MUST run `gitnexus_context({name: "target"})` to see all incoming/outgoing refs, then `gitnexus_impact({target: "target", direction: "upstream"})` to find all external callers before moving code.
- After any refactor: run `gitnexus_detect_changes({scope: "all"})` to verify only expected files changed.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Tools Quick Reference

| Tool | When to use | Command |
|------|-------------|---------|
| `query` | Find code by concept | `gitnexus_query({query: "auth validation"})` |
| `context` | 360-degree view of one symbol | `gitnexus_context({name: "validateUser"})` |
| `impact` | Blast radius before editing | `gitnexus_impact({target: "X", direction: "upstream"})` |
| `detect_changes` | Pre-commit scope check | `gitnexus_detect_changes({scope: "staged"})` |
| `rename` | Safe multi-file rename | `gitnexus_rename({symbol_name: "old", new_name: "new", dry_run: true})` |
| `cypher` | Custom graph queries | `gitnexus_cypher({query: "MATCH ..."})` |

## Impact Risk Levels

| Depth | Meaning | Action |
|-------|---------|--------|
| d=1 | WILL BREAK — direct callers/importers | MUST update these |
| d=2 | LIKELY AFFECTED — indirect deps | Should test |
| d=3 | MAY NEED TESTING — transitive | Test if critical path |

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/AgentsArena/context` | Codebase overview, check index freshness |
| `gitnexus://repo/AgentsArena/clusters` | All functional areas |
| `gitnexus://repo/AgentsArena/processes` | All execution flows |
| `gitnexus://repo/AgentsArena/process/{name}` | Step-by-step execution trace |

## Self-Check Before Finishing

Before completing any code modification task, verify:
1. `gitnexus_impact` was run for all modified symbols
2. No HIGH/CRITICAL risk warnings were ignored
3. `gitnexus_detect_changes()` confirms changes match expected scope
4. All d=1 (WILL BREAK) dependents were updated

## Keeping the Index Fresh

After committing code changes, the GitNexus index becomes stale. Re-run analyze to update it:

```bash
npx gitnexus analyze
```

If the index previously included embeddings, preserve them by adding `--embeddings`:

```bash
npx gitnexus analyze --embeddings
```

To check whether embeddings exist, inspect `.gitnexus/meta.json` — the `stats.embeddings` field shows the count (0 means no embeddings). **Running analyze without `--embeddings` will delete any previously generated embeddings.**

> Claude Code users: A PostToolUse hook handles this automatically after `git commit` and `git merge`.

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->