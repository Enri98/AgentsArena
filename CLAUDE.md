# AgentsArena — Project Context

Python 3.11 library powering an agent-vs-agent arena for two-seat games — sequential or simultaneous (joint turns, Phase 41), deterministic or stochastic (chance nodes, Phase 37), with perfect or hidden information (per-seat views, Phase 38). **v1 milestone reached** (Phases 0-35): simulation core, local runtime, terminal CLI, local Ollama agents, WebSocket server, reference Python SDK, resilience (deadlines/heartbeats/reconnect), structured logging, public-deployment recipe, and an MCP server layer. **v2 (Phases 36-42)** added spectators, rate limits, chance nodes, hidden information, Liar's Dice, transcript persistence, simultaneous moves, a packaged TypeScript SDK (`sdk-ts/`), and scaffold templates per game kind. Real auth, a designed web UI, Prometheus metrics, OpenTelemetry tracing, and lobby/matchmaking remain deferred.

> Source of truth for plan + status: `IMPLEMENTATION_PLAN.md`. Working rules + style: `AGENTS.md`. Wire protocol: `docs/NETWORK_PROTOCOL.md`. Adapter boundaries: `docs/ADAPTER_BOUNDARIES.md`. Cross-session handoff: `docs/MATCH_ARENA_HANDOFF.md`.

> **Activate `.venv` before running any script.** Verify with `.\.venv\Scripts\ruff.exe check .`, `.\.venv\Scripts\python.exe -m mypy` and `.\.venv\Scripts\pytest.exe -q`.

## Layered architecture (strict, downward-only deps)

| Layer | Package | Responsibility |
|-------|---------|---------------|
| Simulation core | `arena.core` | Types, seats, exceptions, events, actions, observations, results, config, `GameDefinition`, `RulesEngine`, `Serializer`, `Registry`. Pure, immutable, no I/O. |
| Games | `arena.games.connect4`, `arena.games.tictactoe`, `arena.games.nim`, `arena.games.pig`, `arena.games.liarsdice`, `arena.games.rps` | Concrete game vertical slices (config, state, action, observation, events, rules, serializer, definition). All registered via `build_default_registry()`. Pig (Phase 37) has chance nodes; Liar's Dice (Phase 39) has hidden information and chance; Rock-Paper-Scissors (Phase 41) has simultaneous moves. |
| Local match | `arena.match` | `LocalMatch`, `TurnRecord`, `start_match` / `apply_match_action`, transcript dump/load/validate, in-process `Policy` protocol, `run_local_match`. Per-match isolated rules engine copy. |
| In-process adapter | `arena.adapters.in_process` | Serialized payload contract: `ObservationRequestPayload`, `ActionResponsePayload`, domain-error payloads, `apply_payload_policy_turn`, `TypedPayloadPolicyAdapter` + `InProcessAgent` for typed local agents. |
| WebSocket adapter | `arena.adapters.websocket` | Pure typed wire-envelope contract for WebSocket transport. Pydantic envelope models, message-type discriminated unions, JSON encode/decode helpers. No I/O. Reuses `arena.adapters.in_process` payload bodies verbatim. |
| Runtime | `arena.runtime` | Pure in-memory `Arena` coordinator, `MatchSession`, opaque `MatchId`, `PlayerRecord`, lifecycle (`created`/`running`/`finished`/`aborted`), runtime events, abort metadata, runtime exceptions, JSON-safe `dump_session_status` / `dump_runtime_transcript` (both `schema_version=3` since Phase 38, with an optional `viewer=` for seat/public views), `format_runtime_session_report`. **Stays deadline-free.** |
| UI adapter | `arena.ui` | Pure adapter over runtime payloads. `build_match_status`, `build_match_transcript`, `build_match_screen`. Reshapes envelopes into screen-level payloads, exposes `state_payload` from snapshots without recomputing rules. |
| CLI | `arena.cli` | Terminal renderer, `python -m arena.cli` replay viewer, `python -m arena.cli.play` interactive driver supporting `human`, `scripted:`, and `ollama:<model>` seats. May depend on `arena.sdk` for `--server-url` remote play. |
| Local agents | `arena.agents.ollama` | Stdlib HTTP client, generic `OllamaAgent` with retry-with-feedback, per-game prompt builders, typed exceptions, `probe_models`. Surfaces retries via the `PolicyRetried` runtime event. |
| Server | `arena.server` | Single-process FastAPI + WebSocket server. `MatchRegistry`, `POST /matches`, `GET /games`, `GET /matches/{id}/public-transcript`, `WS /matches/{id}/play`, `WS /matches/{id}/spectate`. Protocol §13 rate limits, match eviction, per-connection outbound queues, the public-transcript store (Phase 40). Owns per-turn deadlines, heartbeats, disconnect grace, structured JSON logging. The **only** layer allowed to instantiate logging at module scope. |
| SDK | `arena.sdk` | Reference Python client for `arena.server`. Both `connect(url, seat, choose=...)` callback form and `Session` loop form. Game-agnostic: actions and observations are JSON. Includes `LocalSession` test helper and reconnect helper. Stays silent (no log output) by default. |
| TypeScript SDK | `sdk-ts/` (`@agents-arena/sdk`) | Phase 42. Standalone npm package on the standard `WebSocket`/`fetch`; shares no code with Python and speaks only `docs/NETWORK_PROTOCOL.md`. `playMatch`, `SeatSession`, `spectate`, `createMatch`, `fetchPublicTranscript`. Tested against the real server by `tests/integration/test_typescript_sdk.py`. |
| MCP server | `arena.mcp` | MCP wrapper exposing the SDK via stdio or HTTP/SSE transports. Tools: `join_match`, `get_observation`, `make_move`, `get_history`, `match_status`. Per-game action JSON schemas. May only import `arena.sdk` and `arena.core`. |

Dependency direction is enforced by architecture tests: `core`/`games` import none of the upper layers; `match` cannot import adapters/runtime/ui; `adapters.in_process` cannot import runtime/ui; `adapters.websocket` may import only `arena.core`, `arena.adapters.in_process` payload models, and `arena.runtime.payloads` (transcripts ride inside `match_finished`/`welcome`); runtime cannot import ui; nothing below `arena.server` may import `arena.server`; nothing below `arena.sdk` may import `arena.sdk`; `arena.sdk` must not import `arena.match`, `arena.adapters.in_process`, `arena.runtime`, `arena.ui`, `arena.cli`, or `arena.server`; `arena.mcp` may only import `arena.sdk`, `arena.core`, and `arena.games` (its per-game adapters need the game ids), and no lower layer may import `arena.mcp`.

## Implementation status

**v1 milestone reached — Phases 0–35 all complete** (per `IMPLEMENTATION_PLAN.md`):
- 0–10 simulation baseline; 11 local match; 12 transcripts; 13 in-process policy protocol; 14 checkpoint; 15 Tic-Tac-Toe; 16 README examples; 17 adapter boundary doc; 18 serialized in-process adapter; 19 typed payload adapter; 20 runtime baseline; 21 runtime/UI contract; 22 formatting helpers; 23 UI adapter boundary; 24 replay viewer; 25 live human play; 26 local Ollama agents.
- 27 network protocol design; 28 `arena.adapters.websocket`; 29 `arena.server` skeleton + `MatchRegistry`; 30 `arena.sdk` reference client; 31 Ollama-over-WS + CLI `--server-url`; 32 resilience (deadlines, heartbeats, disconnect grace, resume tokens); 33 structured JSON logging; 34 public deployment (Dockerfile, fly.toml, `examples/run_remote_demo.py`); 35 MCP server (`arena.mcp`, stdio + HTTP/SSE).

Outside the numbered roadmap: `arena.games.nim` (commit `3da879a`) is registered in the default registry and exercised by the remote demo.

**Post-v1 work already landed** (not part of the numbered roadmap):
- `68b011a` — per-layer adapter registries. `arena.cli.games`, `arena.mcp.games`, and `arena.agents.ollama._adapters` each expose a registry that per-game modules register into at import time, replacing hand-maintained `if game_id == ...` ladders. **New games must register with each layer's registry rather than adding dispatch branches.**
- `a408787` — `docs/ADDING_A_GAME.md` plus a scaffold generator: `python -m arena.games.scaffold`. Since Phase 42, `--kind chance|hidden|simultaneous` generates a working game of that kind (templates in `arena/games/scaffold/templates/`) with adapters and a contract test.
- `cce1846` — `docs/RFC_IMPERFECT_INFORMATION.md`, a draft v2 RFC proposing Phases 36-40 (per-seat snapshots, `schema_version` 1→2, spectator endpoint, Liar's Dice exemplar). **Draft only — not approved, no code attached.**

**Known gaps:**
- ~~§13 rate limits~~ and ~~CI~~ closed by Phase 36 (`arena.server.rate_limits`, `.github/workflows/ci.yml`).
- Nothing is deployed. `fly.toml` still carries the placeholder `app = "arena-server"`, and the Phase 34 public-server acceptance run has never been executed for real.

Open items: no v1 follow-ups remain. Future work is the v2 backlog (see "Deferred to v2" below) plus the gaps above.

## Core design rules (do not violate)

- Frozen dataclasses for in-memory domain state/actions; Pydantic v2 for config + boundary payloads + JSON Schema.
- Integer seat ids inside the simulation core. Player names/labels live in runtime/UI/server layers.
- Store only minimum authoritative state; derive legality, terminal, winners on demand.
- Chance is nature's action (`arena.core.chance`): engines implement `is_chance_node` / `sample_chance` / `apply_chance`, serializers `dump_/load_chance_outcome`. `arena.match` drains chance nodes as part of stepping, so a live match never rests at one; `current_seat` keeps its signature.
- `apply_action(...)` revalidates legality defensively; raises typed domain exceptions (`WrongPlayer`, `IllegalAction`, `GameFinished`, `InvalidConfig`, ...).
- Serialize only at boundaries via dedicated `Serializer`; every accepted move yields a full post-move snapshot, and snapshots must rehydrate.
- Runtime aborts wrap non-result failures while preserving the original `ArenaCoreError` as cause.
- Runtime payload and wire `schema_version` is `4` since Phase 41 (decoders accept `1`-`4`); any incompatible change must bump it explicitly.
- Simultaneous moves are joint turns (`arena.core.simultaneous`): engines expose `acting_seats` / `apply_joint_action`; `arena.match.apply_match_joint_action` commits one turn carrying every acting seat's action. **No seat's choice is ever in state, a transcript, or a frame before every acting seat has chosen**, so joint turns need no redaction. `current_seat` keeps its signature; callers that need the truth ask `acting_seats`.
- **Everything sent to a viewer is built per viewer** (Phase 38): a viewer is a seat or `None` (the public). Only the server holds a full transcript of a hidden-information game; seats get `view: "seat"` payloads, spectators `"public"`. Use the `*_for_viewer` helpers in `arena.core.public_view` / `arena.match` / `arena.runtime`; never send `_build_snapshot` / `dump_match_transcript` output to a client directly.
- **Per-turn deadlines and wall-clock timeouts live exclusively in `arena.server`. `arena.runtime` stays deadline-free.** Server-enforced expiry produces an existing-style runtime abort with reason `turn_deadline_expired`.
- **Match identity is an unguessable opaque token** (`secrets.token_urlsafe(16)`, >=128 bits of entropy). In v1 there is no auth: possession of the `match_id` is the capability.
- **Structured logging at module-load scope is allowed only in `arena.server`.** Lower layers may use `logging` lazily inside functions when explicitly opted in. The SDK stays silent by default.
- **`docs/NETWORK_PROTOCOL.md` is the language-agnostic source of truth for the wire protocol.** The Python and TypeScript SDKs are reference implementations, not the spec.
- The wire format is JSON over WebSocket; this is not configurable.
- Architecture/import-boundary tests are load-bearing — do not introduce upward imports.

## v2 roadmap (approved 2026-09-22)

Phases 36-42 are specified in `IMPLEMENTATION_PLAN.md` under "v2 roadmap". Order:
36 spectator endpoint + transport refactor + §13 rate limits + CI (v1 wire, no bump) →
37 chance-node primitive (**bump to `schema_version=2`**) →
38 imperfect-information contract (**bump to 3**) → 39 Liar's Dice →
40 transcript persistence + `GET /matches/{id}/public-transcript` → 41 generalized turn loop
(**bump to 4**) → 42 docs + packaged TypeScript SDK.

Phase 36 ✅ (2026-09-23, v1 wire). Phase 37 ✅ (2026-09-24, wire `schema_version=2`): chance
nodes, `kind`/`outcome` transcript turns, multi-version decode, and Pig.

Phase 38 ✅ (2026-09-24, wire `schema_version=3`): per-seat views, event visibility,
per-recipient broadcast, seat-scoped transcripts, reconnect replay, server turn cap.

Phase 39 ✅ (2026-09-24): Liar's Dice (`arena.games.liarsdice`), hidden information plus chance,
proven over the wire and with real Ollama agents.

Phase 40 ✅ (2026-09-25): public transcripts of ended matches persist
(`arena.server.transcript_store`: memory by default, `file:` / `sqlite:` durable) and are served
at `GET /matches/{id}/public-transcript`. Only the public view is ever stored. A pre-phase
adversarial review fixed a seat-hijack leak, MCP cross-client reads, unbounded turn deadlines,
and a dozen robustness gaps (see the plan's Phase 40 Slice 0).

Phase 41 ✅ (2026-09-25, wire `schema_version=4`): simultaneous moves. A round where
several seats act at once is one **joint turn** (`arena.core.simultaneous`:
`acting_seats`, `apply_joint_action`; `kind: "joint"` with an `actions` map). The server
asks every acting seat at once, each with its own deadline, retries, and grace. Exemplar:
Rock-Paper-Scissors (`arena.games.rps`).

Phase 42 ✅ (2026-09-25): packaged TypeScript SDK (`sdk-ts/`), scaffold `--kind
chance|hidden|simultaneous`, and docs reconciled with v4 (`docs/NETWORK_PROTOCOL.md` consolidated,
every claim checked against the code, superseded shapes in appendices).

**The v2 roadmap is complete.** No numbered phase is active. The library basics landed after it:
packaging metadata and console scripts, `py.typed`, `arena.__version__`, `mypy` in CI (clean,
configured in `pyproject.toml`), a release workflow, CHANGELOG / CONTRIBUTING / SECURITY. See the
known gaps in `docs/MATCH_ARENA_HANDOFF.md`.

**Owner rule (2026-09-24): dispatch adversarial reviewer subagents between one feature and the
next**, and fix confirmed findings before moving on.

Three hard constraints discovered by adversarial review, verified against the code:
- **A slow spectator must not be able to stall a match.** `_broadcast` (`runtime_bridge.py:188`)
  awaits `send_text` sequentially inside `run_match`; a blocked send suspends the driver while the
  per-turn deadline keeps running, aborting the match and blaming an innocent seat. Spectators need
  bounded per-connection outbound queues with their own writer tasks.
- **Never put a game's RNG seed in config or state.** `send_welcome` dumps `match_config` to both
  seats, `_build_snapshot` embeds config in every `SnapshotEnvelope`, and every `post_snapshot`
  carries the full state. Either would let a seat predict every roll. The generator lives on
  `LocalMatch.rng` only (Phase 37); transcripts record chance *outcomes*, and replay applies them.
- **§13 rate limits are a prerequisite of the spectator endpoint, not a follow-on.** An
  unauthenticated unlimited fan-out endpoint is exactly what §13 exists to bound.

Two items moved OUT of the v2 deferral list by owner decision: **transcript persistence**
(Phase 40, prerequisite for the HTTP transcript endpoint) and the **spectator endpoint**
(Phase 36 — the URL no longer closes with `4404`).

## Still deferred

- Real authentication, tokens, or accounts
- A designed web spectator **UI** (Phase 36 shipped functional viewer glue at `examples/spectator/`, not a product surface)
- Lobby, matchmaking, tournaments
- Prometheus metrics endpoint
- OpenTelemetry tracing
- Anthropic-SDK-backed agent
- Third-party game registration

## Testing rules (hard-won — do not relearn these)

- **One WebSocket per Starlette `TestClient` test.** A test driving two live WS sessions through a
  single TestClient shares one anyio portal and deadlocks nondeterministically on the receive side.
  This made the whole suite hang in ~75% of full runs. Anything needing two live sockets belongs in
  `tests/integration/`, which runs a real uvicorn server over real TCP via the `running_server`
  fixture.
- **Always context-manage `TestClient`** (`with TestClient(app) as client:`). Unclosed clients leak
  portal threads across the session.
- **Pass short `per_turn_deadline_ms` / `disconnect_grace_ms` in tests.** At the 30 s production
  default, a test that abandons a match leaves `run_match` parked for 30 s.
- **Integration tests cannot catch entry-point bugs: run the real stack after server changes.** Every
  test server uses uvicorn `ws="websockets-sansio"`; `python -m arena.server` (and the Dockerfile) used
  the default implementation, which corrupts receives on cancellation, and aborted *every* real match
  until Phase 38. The entry point now pins `UVICORN_WS_IMPL`. Check with `python -m arena.server` plus
  `examples/run_remote_demo.py --game pig` against local Ollama.
- **`/schemas/payloads` is pinned by a golden file** (`tests/unit/server/golden/`). Tightening a
  payload model with a `Literal` or a bound changes the published JSON Schema, which must stay
  byte-stable within a wire version: validate in a validator instead, or bump the version.
- `pytest-timeout` is configured in `pyproject.toml` (`--timeout=120 --timeout-method=thread`) so a
  hang fails instead of blocking CI forever. The thread method is required: signal-based timeouts
  do not exist on Windows.

## Working workflow

1. Re-read the relevant section of `IMPLEMENTATION_PLAN.md` and only expand the current slice.
2. Implement the smallest coherent change; add/update focused unit tests near the code.
3. Run ruff + pytest from the venv.
4. Update the plan's slice status + handoff docs when a slice completes.
5. Do not skip ahead, do not refactor unrelated modules, do not introduce v2-deferred infrastructure (see list above).
6. When adding a new game, follow `docs/ADDING_A_GAME.md`.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **AgentsArena** (5232 symbols, 17432 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
