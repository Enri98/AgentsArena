# Runtime / UI Contract Handoff

Use this note to start the next planning discussion after the runtime match/session baseline.

## Current Baseline

Implemented and verified:
- `arena.core`: pure simulation abstractions, typed domain exceptions, serializers, registry, results, observations, and events
- `arena.games.connect4`: complete deterministic perfect-information vertical slice
- `arena.games.tictactoe`: second complete deterministic perfect-information vertical slice
- `arena.match`: immutable local match execution, turn records, snapshots, transcript dump/load/validation, and observation-based in-process policies
- `arena.adapters.in_process`: pure serialized in-process adapter payload contract plus typed convenience adapter
- `arena.runtime`: pure in-memory arena/session coordination with match ids, player records, lifecycle states, runtime events, abort metadata, runtime exceptions, local session start/step/run, wrapped runtime transcripts, and UI-ready session status payloads

No networking, persistence, subprocesses, timeouts, auth, matchmaking, concrete UI rendering, or remote-agent protocols have been added.

## Working Assumption

The simulation and pure local runtime layers are complete enough for the current deterministic
perfect-information scope. The next discussion should decide what the UI-facing contract should expose
before building UI code.

## Key Boundary Decision

`arena.runtime` already wraps `LocalMatch` with match identity, players, lifecycle, runtime events,
abort metadata, and JSON-safe status/transcript envelopes. The next layer should not add rendering logic
inside `arena.core`, `arena.games`, `arena.match`, or the rule engines.

Candidate Phase 21 responsibilities:
- audit and stabilize `dump_session_status(...)` as the primary UI status contract
- audit and stabilize `dump_runtime_transcript(...)` as the transcript/history contract
- decide whether UI consumers need a board-oriented derived payload, or should read `latest_snapshot`
- decide how runtime events should be presented to UI/CLI consumers without duplicating game-domain events
- decide whether result and abort payloads are sufficient for user-facing display
- define schema/version expectations for runtime payload compatibility
- add tests for payload shape stability and UI-facing edge cases

Responsibilities still deferred unless explicitly planned:
- remote agents
- APIs
- databases
- stale-version handling
- clocks, deadlines, and timeout outcomes
- auth
- matchmaking queues
- tournaments
- concrete UI rendering or component state

## Questions For The Next Session

Answer these before writing code:
- What exact fields does the first UI need for the match screen?
- Is `latest_snapshot` enough for board rendering, or should runtime expose a game-neutral board/status view?
- Should human-readable transcript formatting live in `arena.runtime`, a new CLI-oriented module, or docs/examples first?
- How should UI distinguish game-domain events from runtime events?
- Should payload shape tests assert full dictionaries, JSON Schema, or both?
- Should Phase 21 update README examples for runtime sessions before adding any UI layer?
- What is the minimum "replay/history" contract needed for the upcoming UI?

## Recommended First Slice

Start with a runtime/UI contract checkpoint:
- document the exact UI-facing runtime payload fields
- add payload stability tests for session status and runtime transcript envelopes
- keep all payloads JSON-safe, versioned, and rendering-agnostic
- do not add web APIs, persistence, subprocesses, remote agents, or concrete UI rendering

If code is added after the checkpoint, keep it pure and local:
- no network
- no persistence
- no subprocesses
- no timeouts
- no auth
- no matchmaking
- no concrete UI rendering
