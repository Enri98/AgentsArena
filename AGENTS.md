# Project context

This repository contains a Python 3.11 library for turn-based game simulation, built incrementally for an agent-vs-agent arena project.

Current scope:
- strictly sequential games
- deterministic games
- perfect-information games
- two built-in games: Connect 4 and Tic-Tac-Toe
- pure simulation core, local match runner, runtime coordinator, UI adapter, terminal CLI, and local Ollama agents are complete
- active roadmap (Phases 27 - 35) introduces remote play: WebSocket server (`arena.server`), reference Python SDK (`arena.sdk`), wire-envelope adapter (`arena.adapters.websocket`), per-turn deadlines, structured logging, and a public-internet acceptance demo
- v2 deferrals (do not introduce in Phases 27 - 35): persistence beyond JSON files, real auth, web spectator UI, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, TypeScript SDK port, Anthropic-SDK-backed agent

The first concrete game is Connect 4. Tic-Tac-Toe is the second.

**REMEMBER TO ACTIVATE THE VIRTUAL ENVIRONMENT `.venv` IN THE BASE ROOT BEFORE RUNNING ANY SCRIPT**


# Main architectural principles

- Keep layers strictly separated.
- The simulation core must remain pure and reusable.
- Do not mix game rules with transport, persistence, UI, or orchestration concerns.
- Prefer small, composable modules over premature framework-like abstractions.
- Implement only what is needed now, but shape interfaces so they can be reused later.

# Core design decisions

- Use **frozen dataclasses** for in-memory domain state and actions.
- Use **Pydantic** for config models, external payloads, serialization-facing models, and JSON Schema emission.
- Use **typed Python domain objects internally**. Do not normalize everything into dicts/JSON inside the simulation core.
- Serialize only at the boundary through dedicated serializer components.
- Use **integer seat ids** in the simulation core.
- Agent names and display labels belong to adapters/UI layers, not the simulation layer.
- Store authoritative state only; derive convenience data on demand where possible.
- `apply_action(...)` must validate defensively and re-check legality.
- Keep orchestration concerns outside the simulation package.

# Intended module split

The codebase should evolve around these separated responsibilities:

- `GameDefinition`
  - static metadata
  - validated game config
  - game registration / lookup
- `RulesEngine`
  - initial state creation
  - legal action generation
  - action validation
  - state transitions
  - terminal/result logic
- `Serializer`
  - state/action/config serialization
  - JSON-safe payload conversion
  - rehydration from serialized snapshots
- `Observation`
  - player-facing view of state
  - separate abstraction even if, for now, it mirrors full state
- domain events
  - emitted by the simulation layer when meaningful rule events occur

# What belongs in the simulation package

Allowed:
- game state
- actions
- rules
- observations
- game config
- game definition / registry
- serializers
- pure domain events
- shared generic test contract

Not allowed in `arena.core`, `arena.games`, `arena.match`, `arena.adapters.*`, `arena.runtime`, `arena.ui`, `arena.cli`, `arena.sdk`, or `arena.agents.*`:
- FastAPI
- WebSocket I/O (envelope types live in `arena.adapters.websocket` but it must not perform I/O)
- DB access
- matchmaking
- auth
- timeouts / wall-clock deadlines (these live exclusively in `arena.server`)
- stale-move handling
- agent connection logic embedded in simulation code
- UI rendering logic
- infrastructure concerns
- module-load-scope `logging.getLogger(__name__)` calls (allowed only in `arena.server`)

# Layer rules introduced by Phases 27 - 35

- `arena.adapters.websocket` is a sibling adapter to `arena.adapters.in_process`. It contains only Pydantic envelope models and pure JSON encode/decode helpers. It must not import `websockets`, `aiohttp`, FastAPI, or perform any I/O.
- `arena.server` is the only layer allowed to enforce per-turn deadlines, heartbeats, disconnect grace periods, and structured logging at module scope. It depends on `arena.runtime`, `arena.adapters.in_process`, `arena.adapters.websocket`, and `arena.ui`. Nothing else may import it.
- `arena.sdk` is the reference Python client. It depends on `arena.core` (for game schemas) and `arena.adapters.websocket` (for envelope types). It must not import `arena.match`, `arena.adapters.in_process`, `arena.runtime`, `arena.ui`, `arena.cli`, or `arena.server`. It produces no log output by default.
- `arena.cli` may consume `arena.sdk` so `python -m arena.cli.play --server-url ...` can drive remote sessions.
- `docs/NETWORK_PROTOCOL.md` is the language-agnostic source of truth for the wire protocol. The Python SDK is a reference implementation, not the spec.
- Match identity is an unguessable opaque token (`secrets.token_urlsafe(16)`, >=128 bits of entropy). In v1 there is no auth: possession of the `match_id` is the capability.
- Wire format is JSON over WebSocket. Not configurable.

# Error handling expectations

Use rich typed domain exceptions where appropriate.

Examples:
- `WrongPlayer`
- `IllegalAction`
- `GameFinished`
- `InvalidConfig`

Do not introduce orchestration-specific exceptions such as stale-version handling into the pure simulation layer.

# Serialization expectations

- Serialized snapshots must be rehydratable.
- Each successful move should eventually correspond to a full serialized post-move snapshot.
- The initial state must also be serializable as a snapshot.
- Prefer explicit, stable serializer code over ad-hoc `dict` construction spread across the codebase.

# Testing expectations

Testing is mandatory, not optional.

Every game implementation should support a shared generic test contract covering at least:
- valid initial state
- valid legal action generation
- rejection of illegal actions
- correct state transition behavior
- terminal/result consistency
- serialization round-trip / rehydration

Add focused unit tests close to the game logic being introduced.

# Connect 4 baseline

Connect 4 is the first implementation and should be treated as the reference vertical slice for the library architecture.

For Connect 4:
- board is stored internally as a tuple of tuples
- actions represent only the move itself
- seats are integers
- game is sequential, deterministic, and perfect-information
- start with one main phase only
- expose structured legal actions, not action masks

# Implementation style

- Favor clarity over cleverness.
- Keep functions small and explicit.
- Avoid hidden side effects.
- Prefer pure transformations and immutable state updates.
- Do not introduce speculative abstractions for future games unless they already reduce duplication now.
- Keep public interfaces intentional and stable.
- Use type hints consistently.

# Working workflow for this repository

When implementing work:
1. follow `IMPLEMENTATION_PLAN.md`
2. expand only the current section into concrete subtasks
3. implement the smallest coherent slice
4. add/update tests
5. verify behavior
6. update the implementation plan if needed
7. then move to the next slice

Do not skip ahead and do not rewrite unrelated modules without a clear reason.

# If unsure

When uncertain, preserve:
1. separation of concerns
2. purity of the simulation core
3. typed internal models
4. minimal authoritative state
5. testability

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
