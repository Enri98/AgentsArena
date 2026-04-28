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

## Phase 21 Decision Checkpoint

Decisions for the first runtime/UI contract slice:
- the first UI status contract should expose `schema_version`, `match_id`, `game_id`, `lifecycle`, `players`, `current_seat`, `turn_count`, `result`, `latest_snapshot`, and `abort`
- `latest_snapshot` is the authoritative rendering input for the current deterministic perfect-information scope; runtime should not add a game-neutral board/view payload yet
- session status should not include runtime event lists; status stays lightweight and current-state oriented, while event history stays in runtime transcripts
- UI distinguishes runtime events from game-domain events by envelope location first: runtime events are top-level `events` in the runtime transcript, while game-domain events remain inside `match_transcript.turns[*].events`
- runtime event payloads should self-identify with `event_scope="runtime"` for stable downstream consumption
- runtime status and transcript payload schemas both pin `schema_version` to the fixed supported value `1`; future incompatible changes should bump the version explicitly
- payload stability should be enforced with explicit full-payload tests for representative session states plus version checks, rather than introducing JSON Schema as the compatibility gate in this slice

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

## Phase 23 UI Adapter Boundary

The first UI boundary is `arena.ui`. It is a pure adapter over `arena.runtime`
payloads and does not import simulation, game, match, transport, persistence, or
rendering code.

Current UI-facing helpers:
- `build_match_status(...)` validates a runtime session status payload and returns
  a deterministic screen-level status payload.
- `build_match_transcript(...)` validates a runtime transcript envelope shape and
  returns screen-level history data with top-level runtime events separated from
  game-domain turn events.
- `build_match_screen(...)` combines matching status and transcript payloads for a
  match screen.

The adapter preserves `latest_snapshot` as the authoritative state envelope and
also exposes `state_payload` as the snapshot's opaque state mapping for board
rendering. It does not recompute game rules or introduce a game-neutral board
model.

## Phase 24 Status

Phase 24 is complete. Delivered:

- `arena.cli` package with a strict import-direction boundary enforced by architecture tests.
- `arena.cli.rendering` — generic ANSI-colored screen renderer consuming `UIMatchScreenPayload` dicts.
- `arena.cli.games.connect4` and `arena.cli.games.tictactoe` — per-game board renderers reading `state_payload`.
- `arena.cli.app` — file-based loader (`render_session_from_files`, `render_all_frames`) that reads status and transcript JSON, validates through `arena.ui`, and renders one or all frames. Frame stepping keeps status at latest state while shifting board and turn-history cursor to the requested turn.
- `arena.cli.__main__` — `python -m arena.cli` entrypoint with `--status`, `--transcript`, `--turn`, and `--all-frames` flags.
- `examples/run_and_render_match.py` — end-to-end script that runs a scripted 4x4 Connect 4 session, dumps both payload files, and prints the final rendered frame.
- Architecture tests confirm no lower layer (`arena.core`, `arena.games`, `arena.match`, `arena.adapters`, `arena.runtime`, `arena.ui`) imports `arena.cli`.
- README section "Terminal replay viewer" documents the example and entrypoint commands.

## Phase 25 Recommendation

The next slice should introduce live human play via a `HumanPolicy` before adding any transport adapter.

Key notes for Phase 25:
- `HumanPolicy` needs an input loop that reads from stdin (or a callback).
- It breaks the determinism constraint for the seat that is human-controlled; golden tests must target only the scripted seat.
- The input loop should be injected as a dependency so tests can provide a scripted input sequence without touching stdin.
- No networking, remote agents, or transport adapters should be added in Phase 25; the goal is interactive in-process play only.
