# AgentsArena — Project Context

Python 3.11 library powering an agent-vs-agent arena for sequential, deterministic, perfect-information games. **v1 milestone reached** (Phases 0-35 complete): simulation core, local runtime, terminal CLI, local Ollama agents, WebSocket server, reference Python SDK, resilience (deadlines/heartbeats/reconnect), structured logging, public-deployment recipe, and an MCP server layer all shipped. Persistence beyond JSON files, real auth, web spectator UI, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, and a TypeScript SDK port are explicitly v2 concerns.

> Source of truth for plan + status: `IMPLEMENTATION_PLAN.md`. Working rules + style: `AGENTS.md`. Wire protocol: `docs/NETWORK_PROTOCOL.md`. Adapter boundaries: `docs/ADAPTER_BOUNDARIES.md`. Cross-session handoff: `docs/MATCH_ARENA_HANDOFF.md`.

> **Activate `.venv` before running any script.** Verify with `.\.venv\Scripts\ruff.exe check .` and `.\.venv\Scripts\pytest.exe -q`.

## Layered architecture (strict, downward-only deps)

| Layer | Package | Responsibility |
|-------|---------|---------------|
| Simulation core | `arena.core` | Types, seats, exceptions, events, actions, observations, results, config, `GameDefinition`, `RulesEngine`, `Serializer`, `Registry`. Pure, immutable, no I/O. |
| Games | `arena.games.connect4`, `arena.games.tictactoe`, `arena.games.nim` | Concrete game vertical slices (config, state, action, observation, events, rules, serializer, definition). All registered via `build_default_registry()`. |
| Local match | `arena.match` | `LocalMatch`, `TurnRecord`, `start_match` / `apply_match_action`, transcript dump/load/validate, in-process `Policy` protocol, `run_local_match`. Per-match isolated rules engine copy. |
| In-process adapter | `arena.adapters.in_process` | Serialized payload contract: `ObservationRequestPayload`, `ActionResponsePayload`, domain-error payloads, `apply_payload_policy_turn`, `TypedPayloadPolicyAdapter` + `InProcessAgent` for typed local agents. |
| WebSocket adapter | `arena.adapters.websocket` | Pure typed wire-envelope contract for WebSocket transport. Pydantic envelope models, message-type discriminated unions, JSON encode/decode helpers. No I/O. Reuses `arena.adapters.in_process` payload bodies verbatim. |
| Runtime | `arena.runtime` | Pure in-memory `Arena` coordinator, `MatchSession`, opaque `MatchId`, `PlayerRecord`, lifecycle (`created`/`running`/`finished`/`aborted`), runtime events, abort metadata, runtime exceptions, JSON-safe `dump_session_status` / `dump_runtime_transcript` (both pinned `schema_version=1`), `format_runtime_session_report`. **Stays deadline-free.** |
| UI adapter | `arena.ui` | Pure adapter over runtime payloads. `build_match_status`, `build_match_transcript`, `build_match_screen`. Reshapes envelopes into screen-level payloads, exposes `state_payload` from snapshots without recomputing rules. |
| CLI | `arena.cli` | Terminal renderer, `python -m arena.cli` replay viewer, `python -m arena.cli.play` interactive driver supporting `human`, `scripted:`, and `ollama:<model>` seats. May depend on `arena.sdk` for `--server-url` remote play. |
| Local agents | `arena.agents.ollama` | Stdlib HTTP client, generic `OllamaAgent` with retry-with-feedback, per-game prompt builders, typed exceptions, `probe_models`. Surfaces retries via the `PolicyRetried` runtime event. |
| Server | `arena.server` | Single-process FastAPI + WebSocket server. `MatchRegistry`, `POST /matches`, `GET /games`, `WS /matches/{id}/play`. Owns per-turn deadlines, heartbeats, disconnect grace, structured JSON logging. The **only** layer allowed to instantiate logging at module scope. |
| SDK | `arena.sdk` | Reference Python client for `arena.server`. Both `connect(url, seat, choose=...)` callback form and `Session` loop form. Ships Connect 4 / Tic-Tac-Toe / Nim schemas. Includes `LocalSession` test helper and reconnect helper. Stays silent (no log output) by default. |
| MCP server | `arena.mcp` | MCP wrapper exposing the SDK via stdio or HTTP/SSE transports. Tools: `join_match`, `get_observation`, `make_move`, `get_history`, `match_status`. Per-game action JSON schemas. May only import `arena.sdk` and `arena.core`. |

Dependency direction is enforced by architecture tests: `core`/`games` import none of the upper layers; `match` cannot import adapters/runtime/ui; `adapters.in_process` cannot import runtime/ui; `adapters.websocket` may import only `arena.core` and `arena.adapters.in_process` payload models; runtime cannot import ui; nothing below `arena.server` may import `arena.server`; nothing below `arena.sdk` may import `arena.sdk`; `arena.sdk` must not import `arena.match`, `arena.adapters.in_process`, `arena.runtime`, `arena.ui`, `arena.cli`, or `arena.server`; `arena.mcp` may only import `arena.sdk` and `arena.core`, and no lower layer may import `arena.mcp`.

## Implementation status

**v1 milestone reached — Phases 0–35 all complete** (per `IMPLEMENTATION_PLAN.md`):
- 0–10 simulation baseline; 11 local match; 12 transcripts; 13 in-process policy protocol; 14 checkpoint; 15 Tic-Tac-Toe; 16 README examples; 17 adapter boundary doc; 18 serialized in-process adapter; 19 typed payload adapter; 20 runtime baseline; 21 runtime/UI contract; 22 formatting helpers; 23 UI adapter boundary; 24 replay viewer; 25 live human play; 26 local Ollama agents.
- 27 network protocol design; 28 `arena.adapters.websocket`; 29 `arena.server` skeleton + `MatchRegistry`; 30 `arena.sdk` reference client; 31 Ollama-over-WS + CLI `--server-url`; 32 resilience (deadlines, heartbeats, disconnect grace, resume tokens); 33 structured JSON logging; 34 public deployment (Dockerfile, fly.toml, `examples/run_remote_demo.py`); 35 MCP server (`arena.mcp`, stdio + HTTP/SSE).

Outside the numbered roadmap: `arena.games.nim` (commit `3da879a`) is registered in the default registry and exercised by the remote demo.

Open items: stdio-subprocess MCP e2e test (Phase 35 follow-up; not v1-blocking). Future work is the v2 backlog (see "Deferred to v2" below).

## Core design rules (do not violate)

- Frozen dataclasses for in-memory domain state/actions; Pydantic v2 for config + boundary payloads + JSON Schema.
- Integer seat ids inside the simulation core. Player names/labels live in runtime/UI/server layers.
- Store only minimum authoritative state; derive legality, terminal, winners on demand.
- `apply_action(...)` revalidates legality defensively; raises typed domain exceptions (`WrongPlayer`, `IllegalAction`, `GameFinished`, `InvalidConfig`, ...).
- Serialize only at boundaries via dedicated `Serializer`; every accepted move yields a full post-move snapshot, and snapshots must rehydrate.
- Runtime aborts wrap non-result failures while preserving the original `ArenaCoreError` as cause.
- Runtime payload `schema_version` is fixed at `1`; any incompatible change must bump it explicitly.
- **Per-turn deadlines and wall-clock timeouts live exclusively in `arena.server`. `arena.runtime` stays deadline-free.** Server-enforced expiry produces an existing-style runtime abort with reason `turn_deadline_expired`.
- **Match identity is an unguessable opaque token** (`secrets.token_urlsafe(16)`, >=128 bits of entropy). In v1 there is no auth: possession of the `match_id` is the capability.
- **Structured logging at module-load scope is allowed only in `arena.server`.** Lower layers may use `logging` lazily inside functions when explicitly opted in. The SDK stays silent by default.
- **`docs/NETWORK_PROTOCOL.md` is the language-agnostic source of truth for the wire protocol.** The Python SDK is a reference implementation, not the spec.
- The wire format is JSON over WebSocket; this is not configurable.
- Architecture/import-boundary tests are load-bearing — do not introduce upward imports.

## Deferred to v2

- Transcript persistence beyond JSON files written by `examples/`
- Real authentication, tokens, or accounts
- Web spectator UI (URL shape `WS /matches/{id}/spectate` reserved; closes with `4404` until v2)
- Lobby, matchmaking, tournaments
- Prometheus metrics endpoint
- OpenTelemetry tracing
- TypeScript SDK port
- Anthropic-SDK-backed agent
- Third-party game registration

## Working workflow

1. Re-read the relevant section of `IMPLEMENTATION_PLAN.md` and only expand the current slice.
2. Implement the smallest coherent change; add/update focused unit tests near the code.
3. Run ruff + pytest from the venv.
4. Update the plan's slice status + handoff docs when a slice completes.
5. Do not skip ahead, do not refactor unrelated modules, do not introduce v2-deferred infrastructure (see list above).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **AgentsArena** (2192 symbols, 6676 relationships, 162 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
