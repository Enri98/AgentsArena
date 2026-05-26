# Match / Arena Handoff

Use this note to start the next planning discussion. Last updated for the Phase 27 entry into the remote-play roadmap.

## Current Baseline

Implemented and verified through Phase 26:
- `arena.core`: pure simulation abstractions, typed domain exceptions, serializers, registry, results, observations, and events
- `arena.games.connect4` and `arena.games.tictactoe`: complete deterministic perfect-information vertical slices
- `arena.match`: immutable local match execution, turn records, snapshots, transcript dump/load/validation, and observation-based in-process policies
- `arena.adapters.in_process`: pure serialized in-process adapter payload contract plus typed convenience adapter
- `arena.runtime`: pure in-memory arena/session coordination, match ids, player records, lifecycle, runtime events (including `PolicyRetried`), abort metadata, wrapped transcripts, UI-ready status payloads
- `arena.ui`: pure adapter producing deterministic screen-level payloads
- `arena.cli`: terminal renderer, replay viewer, interactive driver supporting `human` / `scripted:` / `ollama:<model>` seats
- `arena.agents.ollama`: stdlib HTTP client, generic `OllamaAgent` with retry-with-feedback, per-game prompt builders, typed exceptions, `probe_models` startup check

No networking, server, SDK, persistence, real auth, web UI, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, Anthropic/OpenAI agents, or TypeScript SDK port have been added.

## Active Phase: 27 - Network Protocol Design Checkpoint

In flight:
- `docs/NETWORK_PROTOCOL.md` is the language-agnostic source of truth for the wire protocol; first pass plus an adversarial-review revision are both shipped
- `IMPLEMENTATION_PLAN.md` extended with Phases 27 - 35 covering protocol doc, `arena.adapters.websocket`, `arena.server` skeleton with `MatchRegistry`, `arena.sdk` reference Python client, Ollama-over-WS port, resilience (timeouts/heartbeats/reconnection), structured logging baseline, public deployment + acceptance demo, and the optional MCP wrapper
- `CLAUDE.md` and `AGENTS.md` updated to reflect the new layer rules and v2 deferrals

Adversarial-review revision (applied to the protocol doc):
- full HTTP request/response shapes for `POST /matches`, `GET /matches/{id}`, `GET /games` in §4.1
- new endpoint `GET /schemas/payloads` (§17) serving JSON Schema for every payload type so non-Python SDKs can codegen against a single source of truth
- new §18 "Message broadcast matrix" disambiguating recipients per message type
- `resume_token` scoped server-side to `(match_id, seat)` and rotated on every resume; mismatch closes `4401`
- match creation locks `per_turn_deadline_ms`, `per_action_retry_budget`, `disconnect_grace_ms`; `welcome` echoes them
- deterministic close ordering on retry-budget exhaustion: `action_rejected(0)` -> `match_state(aborted)` -> `match_aborted` -> WS close `1000`
- atomicity rule for `running -> finished/aborted` transitions; "action arrives after terminal" rule
- per-connection FIFO + per-`turn_id` retry-counter decrement semantics
- per-match concurrent-connection cap (4) added to §13
- explicit v1 assumption: protocol supports public-move perfect-information games only; private-information games require a v2 extension
- "byte-identical replay" claim replaced with "logically equivalent state"

The v1 acceptance demo is two local Ollama agents on the user's laptop both connecting to a publicly reachable `arena.server`, completing one clean Connect 4 match and one deliberate-abort scenario.

## Locked Decisions for Phases 27 - 35

- WebSocket only; JSON wire format; not configurable
- per-turn deadlines live in `arena.server`; `arena.runtime` stays deadline-free
- match identity uses `secrets.token_urlsafe(16)`; possession of the id is the only capability in v1
- creator becomes seat 0; joiner becomes seat 1
- `MatchRegistry` from day one; no single-hardcoded-match intermediate
- SDK ships both `connect(...)` callback form and `Session` loop form so MCP layering does not require a redesign
- SDK ships Connect 4 / Tic-Tac-Toe schemas directly; no handshake-time fetching
- structured JSON logging only in `arena.server`; lower layers stay quiet
- v2 deferrals: persistence beyond JSON files, real auth, web spectator UI, Prometheus, OpenTelemetry, lobby/matchmaking, TypeScript SDK port, Anthropic agent, third-party game registration

## Next Entry Point

Phase 28 — `arena.adapters.websocket` payload contract. Sibling to `arena.adapters.in_process`, pure typed envelopes, no I/O. See `IMPLEMENTATION_PLAN.md` Phase 28 for slice breakdown.

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

## Phase 25 Status

Phase 25 is complete. Delivered:

- `arena.cli.policies` — `HumanPolicy` (stdin/stdout-injected, parser-delegating) and `HumanQuit` sentinel exception (inherits `BaseException` to bypass the runtime's `except Exception` handler and reach the driver cleanly).
- `arena.cli.games.connect4.parse_input` and `arena.cli.games.tictactoe.parse_input` — pure per-game input parsers; return the typed action or `None` to reprompt.
- `arena.cli.play` package — `play_match(...)` interactive driver that creates/starts/steps a session, renders each frame, catches `HumanQuit`/`KeyboardInterrupt`, calls `Arena.abort_session(...)` with `AbortReason.USER_QUIT` or `AbortReason.USER_INTERRUPT`, writes `status.json` and `transcript.json`, and returns 0 on finish or 1 on abort.
- `arena.cli.play.__main__` — `python -m arena.cli.play` entrypoint with `--game`, `--seat-0`, `--seat-1` (`human` or `scripted:<actions>`), `--out-dir`, and Connect 4 board flags.
- `AbortReason.USER_QUIT` and `AbortReason.USER_INTERRUPT` added to `arena.runtime.models.AbortReason` (additive, no existing tests affected).
- Architecture tests extended to exercise `arena.cli.play` and `arena.cli.policies` imports.
- README "Play locally" section added.
- 398 tests pass (371 before Phase 25).

Abort path: `HumanQuit` (and raw `KeyboardInterrupt`) propagate past `step_session`'s `except Exception` guard because `HumanQuit` inherits `BaseException`. The driver catches both in inner and outer handlers, calls `Arena.abort_session(...)` with the correct reason, and always writes both JSON files before returning.

## Phase 26 Recommendation

The next slice should add an Anthropic-SDK-backed `InProcessAgent` so LLM opponents can play against the human through the existing typed adapter chain.

Key notes for Phase 26:
- The existing `TypedPayloadPolicyAdapter` already wraps any `InProcessAgent[ObservationT, ActionT]` into the `PayloadPolicy` contract the runtime expects — no schema change needed.
- Build a concrete `AnthropicAgent` (or `ClaudeAgent`) in a new `arena.agents` package that receives a typed observation, formats it as a user message, calls the Anthropic SDK, and parses the model's response into a typed action.
- The user will need an Anthropic API key; the Max plan does not cover programmatic API access — the key must be set via `ANTHROPIC_API_KEY` environment variable.
- Extend `--seat-0`/`--seat-1` in `arena.cli.play.__main__` to accept `llm` (or `claude`) alongside `human` and `scripted:...`.
- Keep the same abort semantics; if the SDK raises an exception, it surfaces as `AbortReason.ADAPTER_ERROR` through the existing handler in `step_session`.

## Phase 26 Status

Implemented and verified (Phase 26 — Local Ollama LLM agent):
- `arena.agents.ollama`: stdlib HTTP client (`OllamaClient`), generic `OllamaAgent` with retry-with-feedback loop, `Connect4PromptBuilder`, `TicTacToePromptBuilder`, typed exceptions (`OllamaIllegalActionError`, `OllamaUnavailableError`, `OllamaModelMissingError`), and `probe_models` startup check
- `arena.runtime.models.PolicyRetried`: new additive frozen-dataclass event; included in the `RuntimeEvent` hierarchy and serialized with `event_scope="runtime"` in transcripts; no `schema_version` bump
- `arena.runtime.session.record_runtime_event`: small public helper to append a runtime event to a session immutably; exported from `arena.runtime`
- `arena.cli.play.play_match`: extended with optional `retry_sink` parameter; after each `complete_turn`, the driver drains seat-keyed lists of `(attempt, reason)` tuples written by agent callbacks and records them as `PolicyRetried` events — keeping `arena.agents` ignorant of runtime internals
- `arena.cli.play.__main__`: `ollama:<model>` seat spec parsing; `--ollama-host`, `--ollama-temperature`, `--ollama-seed`, `--ollama-max-retries` flags; `probe_models` startup check with `sys.exit(2)` on failure
- `examples/run_ollama_vs_ollama.py`: importable `run()` driving `llama3.2:latest` vs `qwen2.5:1.5b` on 4x4 Connect 4
- Architecture boundary test: `tests/unit/architecture/test_agents_boundaries.py` enforces neither upper layers import `arena.agents` nor `arena.agents` imports `arena.match`, `arena.adapters`, `arena.runtime`, or `arena.ui`

## Phase 27 Recommendation

Phase 27: Anthropic-SDK-backed agent reusing the `PromptBuilder` interface. Build `AnthropicAgent` in `arena.agents.anthropic` implementing `InProcessAgent` and accepting any `PromptBuilder` from Slice 2 — the same Connect4PromptBuilder and TicTacToePromptBuilder should work without modification. The user will need `ANTHROPIC_API_KEY`; the Max plan does not cover programmatic API access.

## Phase 34 Status — v1 milestone reached

Implemented and verified:
- `Dockerfile` (multi-stage `python:3.11-slim`, non-root user, `EXPOSE 8080`, `HEALTHCHECK` hitting `/games`, runs `python -m arena.server --host 0.0.0.0 --port 8080`).
- `fly.toml` (shared-cpu-1x, 256MB, `auto_stop_machines = "stop"`, `min_machines_running = 0`, `force_https = true`).
- `.dockerignore` excluding `.venv`, tests, runs, docs, `.gitnexus`, `.claude`, cache dirs.
- `docs/DEPLOYMENT.md` — beginner-friendly Fly.io walkthrough from zero (account, `flyctl` install on Windows, launch/deploy, logs, teardown). Caddy/VPS appendix for self-hosters.
- `pyproject.toml` `[server]` extras now include `websockets>=13` (required by uvicorn's WS backend at runtime).
- `arena.agents.ollama.run_remote_seat(server_url, seat, game_id, model, ...)` async helper bundling Ollama + SDK wiring for a single seat. Connects through `arena.cli.remote` (existing `make_typed_agent_choose` + new `run_remote_seat_async`) so no architecture boundary changes were needed.
- `examples/run_remote_demo.py` driving two `run_remote_seat` calls concurrently. Supports `--game connect4|tictactoe|nim`, `--abort-after-turns N` (seat-1 raises after N turns to trigger `peer_disconnected`), `--skip-probe`. Dumps both transcripts and validates them.
- `tests/integration/test_remote_demo.py` — happy path (Connect 4), abort path with `reason="peer_disconnected"`, Nim smoke. All use the existing `running_server` fixture + stub `OllamaClient`.
- README "Watch two LLMs play remotely" section pointing at `examples/run_remote_demo.py` and `docs/DEPLOYMENT.md`.

Side context: Nim (`src/arena/games/nim/`) was added outside the documented roadmap in commit `3da879a`. It is now exercised by the remote demo and integration tests.

Acceptance:
- Local Docker build + run produces a working server reachable at `http://127.0.0.1:8080/games`.
- Fly.io deploy walkthrough documented end-to-end; manual public-server run is reproducible.
- Abort scenario produces an `aborted` transcript whose abort metadata `reason == "peer_disconnected"` and which passes `validate_runtime_transcript`.

Skipped: TLS terminated by `arena.server` itself (always done by Fly's edge or Caddy); managed deployment to providers beyond the Fly.io example; transcript persistence beyond writing to `--out-dir`.

## Phase 35 Status — MCP layer (optional v1 extension)

Implemented and verified:
- New top-level layer `src/arena/mcp/` exposing `arena.sdk.Session` through five MCP tools — `join_match`, `get_observation`, `make_move`, `get_history`, `match_status` — backed by a `SessionRegistry` with per-`(match_id, seat)` background `_recv_loop` and asyncio.Queue.
- `src/arena/mcp/schemas.py` ships JSON Schema dicts for Connect 4, Tic-Tac-Toe, and Nim action inputs.
- Transports: `python -m arena.mcp` defaults to stdio (Claude Desktop); `--http --host --port` runs the HTTP/SSE transport with a loud stderr warning when bound to a non-localhost host (no auth in v1).
- `pyproject.toml` `[mcp]` optional dep group adds `mcp>=1.0`.
- `tests/unit/architecture/test_mcp_boundaries.py` enforces `arena.mcp` may only import `arena.sdk` and `arena.core`; no lower layer imports `arena.mcp`. The module-load-scope logger ban is extended to `arena.mcp`.
- `tests/integration/test_mcp_integration.py` drives Connect 4 through the five tool handlers directly (no transport subprocess), verifies happy-path completion, registry auto-purge on terminal events, and error response for unknown match.
- README "Play with Claude Desktop" section with a `claude_desktop_config.json` snippet and the HTTP/SSE no-auth warning.
- `arena.sdk/` source unchanged — Phase 35 acceptance criterion satisfied.

Follow-up shipped:
- True stdio subprocess e2e test (transport-level MCP handshake) landed in commit `7fafbb0` as `tests/integration/test_mcp_stdio_e2e.py`, complementing the direct in-process tool test.

Phase 35 does not block the v1 milestone; v1 = Phase 34 done.

