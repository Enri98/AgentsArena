# Match / Arena Handoff

Cross-session handoff note. **Last updated 2026-09-22** — rewritten from an append-only log into a
current-state document. Historical phase decisions are preserved in the appendix.

## 1. Current state

**v1 is complete and green.** Verified 2026-09-22 on `main` (clean tree, `55ada5a`):

- `ruff check .` — all checks passed
- `pytest -q` — **675 passed**
- ~12.8k LOC in `src/`, ~13.3k in `tests/` across 86 test files

Eleven layers ship, with import direction enforced by architecture tests:

| Layer | State |
|-------|-------|
| `arena.core` | Pure simulation abstractions, typed domain exceptions, serializers, registry, results, observations, events |
| `arena.games.{connect4,tictactoe,nim}` | Three complete deterministic perfect-information vertical slices |
| `arena.games.scaffold` | `python -m arena.games.scaffold` generates a new game package skeleton |
| `arena.match` | Immutable local match execution, turn records, snapshots, transcript dump/load/validate |
| `arena.adapters.in_process` | Serialized in-process payload contract + typed convenience adapter |
| `arena.adapters.websocket` | Pure typed wire envelopes, no I/O |
| `arena.runtime` | In-memory arena/session coordination, lifecycle, runtime events, abort metadata, JSON-safe payloads. Deadline-free |
| `arena.ui` | Pure adapter producing deterministic screen-level payloads |
| `arena.cli` | Terminal renderer, replay viewer, interactive driver (`human` / `scripted:` / `ollama:<model>`), `--server-url` remote play |
| `arena.agents.ollama` | Stdlib HTTP client, `OllamaAgent` with retry-with-feedback, per-game prompt builders, `probe_models` |
| `arena.server` | FastAPI + WebSocket, `MatchRegistry`, per-turn deadlines, heartbeats, disconnect grace, resume tokens, structured JSON logging |
| `arena.sdk` | Reference Python client (callback + loop forms), `LocalSession` helper, reconnect helper. Silent by default |
| `arena.mcp` | MCP wrapper over the SDK. Five tools, stdio + HTTP/SSE transports, per-game action JSON schemas |

Deployment artifacts exist but have never been used against a real host: `Dockerfile`, `fly.toml`,
`.dockerignore`, `docs/DEPLOYMENT.md`.

## 2. Known gaps

These do not invalidate the v1 claim. They all block a public launch.

1. **Protocol §13 rate limits are specified but not implemented.** No per-IP connection cap, no
   match-creation throttle, no per-match connection cap; close code `4429` appears nowhere in
   `src/`. With no auth in v1, this is the top pre-deployment item.
2. **No CI.** No `.github/` workflow exists.
3. **Never deployed.** `fly.toml` still carries the placeholder `app = "arena-server"`.
4. **SDK not on PyPI.** Joining a match requires cloning the repo — the largest gap between the
   shipped code and the goal of an open arena.

## 3. Locked decisions (still binding)

- WebSocket only; JSON wire format; not configurable.
- Per-turn deadlines live in `arena.server`; `arena.runtime` stays deadline-free.
- Match identity is `secrets.token_urlsafe(16)`; possession of the id is the only v1 capability.
- Creator becomes seat 0; joiner becomes seat 1.
- `MatchRegistry` from day one; no single-hardcoded-match intermediate.
- SDK ships both `connect(...)` callback form and `Session` loop form.
- SDK ships game schemas directly; no handshake-time fetching.
- Structured JSON logging only in `arena.server`; lower layers stay quiet.
- Runtime payload `schema_version` is pinned at `1`; incompatible changes must bump it explicitly.
- `docs/NETWORK_PROTOCOL.md` is the language-agnostic source of truth; the Python SDK is a
  reference implementation, not the spec.
- **New games register with each layer's adapter registry** (`arena.cli.games`, `arena.mcp.games`,
  `arena.agents.ollama._adapters`) rather than adding dispatch branches. See
  `docs/ADDING_A_GAME.md`.

## 4. Open decisions blocking the next phase

**Resolved 2026-09-22.** All seven RFC questions (plus an eighth on turn-loop sequencing) were
answered by the owner, and Phases 36-42 are now specified in `IMPLEMENTATION_PLAN.md` under
"v2 roadmap". `docs/RFC_IMPERFECT_INFORMATION.md` is superseded as a plan, retained as analysis.

**Phase 36 is complete** (2026-09-23), on the v1 wire with no `schema_version` bump. Shipped:
CI, all four protocol §13 rate limits, `MatchRegistry` eviction, the public-view contract, the
`MatchConnections` registry, per-connection bounded outboxes with writer tasks, the live
`WS /matches/{id}/spectate` channel, and a zero-dependency browser viewer at
`examples/spectator/`. 714 tests pass.

One item was deliberately deferred out of Slice 2: the **match-owned driver task**. `run_match` is
still owned by the seat-1 handler. Both things that motivated the refactor — the test flake and
spectator attachment — were solved without it, and its only remaining consumer is Phase 41s
simultaneous-move loop. Build it there rather than speculatively.

**Phase 37 is complete** (2026-09-24), carrying the wire bump to `schema_version=2`. Shipped: the
chance-node contract (`arena.core.chance`), `kind`/`outcome` transcript turns, load-bearing
`turn_committed.events`, multi-version decode, and **Pig** (`arena.games.pig`) as the exemplar game,
registered in every adapter registry. 821 tests pass.

**The chance seed is private to the match.** The first draft put `ChanceRng(seed, counter)` in game
state. But state is broadcast as `post_snapshot`, so anyone could run it forward and predict every
roll. Chance is now nature's action: `sample_chance(state, rng)` draws an outcome live,
`apply_chance(state, outcome)` applies and revalidates it, and the generator lives on
`LocalMatch.rng`, never in state, config, or any payload. Transcripts record outcomes, and replay
(`start_replay_match`) applies them without the seed.

**Phase 38 is complete** (2026-09-24), carrying the bump to `schema_version=3`. Every payload a
client receives is now built for that recipient. A viewer is a seat, or `None` for the public.
Snapshots, chance outcomes, domain events (`DomainEvent.visible_to`), transcripts (`view`:
full/seat/public), and `welcome.match_config` are all redacted per viewer, and a reconnect's
`welcome.transcript` replays the seat's own history (§11). The server's gate refusing
hidden-information games is lifted. Proof: over real TCP, two matches that differ only in seat 1's
secret give byte-identical frames to seat 0 and to a spectator.

**Adversarial review is now part of the workflow** (owner rule, 2026-09-24): after each slice,
reviewer subagents attack it and confirmed findings are fixed before the next slice. The first two
rounds found real problems:
- the Slice 1 leak contract let leaky games pass;
- the transcript validator accepted forged shapes;
- Pig could run forever (now bounded by a server turn cap);
- spectators could get duplicate turns;
- MCP `make_move` confirmed a stale turn;
- the browser spectator had been refused since Phase 37.

Active phase: **39 — Liar's Dice**. No wire bump. Everything it needs exists: chance nodes for the
roll, per-seat redaction, private events, and the indistinguishability contract. Its CLI adapter
must render the live game from the human seat's view; the local `arena.cli.play` still shows full
state.

The Phase 36-38 specs were revised on 2026-09-22 after an adversarial review that checked every
claim against the code. Three findings are worth carrying forward, because each is easy to
rediscover the hard way:

- **A slow spectator can abort a match.** `_broadcast` (`runtime_bridge.py:188`) awaits `send_text`
  sequentially inside `run_match`; one blocked send suspends the driver while the per-turn deadline
  timer keeps running, and the active seat is blamed for `turn_deadline_expired`.
- **A seed in config is public — and so is a seed in state.** `send_welcome` dumps `match_config` to
  both seats, `_build_snapshot` embeds config in every `SnapshotEnvelope`, and every
  `post_snapshot` carries the full state. Phase 37 keeps the generator on `LocalMatch` for this reason.
  Phase 38's `dump_state_for_seat` covers `state`, not `config`, and a chance turn's `outcome` can
  itself be private (Liar's Dice's opening roll).
- ~~**`_handle_reconnect` never replays the transcript**~~ Fixed in Phase 38:
  `welcome.transcript` carries the seat's own history. Still a known limitation: only the active
  seat's reconnect is fully supported. An off-turn disconnect is noticed on that seat's turn, so an
  early reconnect can miss frames. The Phase 41 match-owned driver is the fix.

Decisions that diverge from the RFC's own recommendations, and are therefore easy to get wrong:
- a **real chance-node primitive** (Phase 37), not seeded init-time randomness
- **spectator ships first** (Phase 36), against perfect-information games where the public view
  equals the full state
- **transcript persistence is in scope** (Phase 40), no longer a v2 deferral
- **simultaneous moves are in scope** but deferred to Phase 41, after Liar's Dice ships

## 5. Still deferred

Real authentication, tokens, or accounts; a designed web spectator UI (Phase 36 ships functional
viewer glue, not a product surface); lobby, matchmaking, tournaments; Prometheus metrics;
OpenTelemetry tracing; Anthropic-SDK-backed agent; third-party game registration; N-player games.

Moved out of deferral by the 2026-09-22 decisions: transcript persistence (Phase 40), the
spectator endpoint (Phase 36), and the TypeScript SDK (Phase 42).

---

# Appendix — historical decision records

Kept because they explain why the current shapes were chosen. Superseded recommendations have been
removed; what remains is decisions that still hold.

## Phase 21 — runtime/UI contract decisions

- The UI status contract exposes `schema_version`, `match_id`, `game_id`, `lifecycle`, `players`,
  `current_seat`, `turn_count`, `result`, `latest_snapshot`, and `abort`.
- `latest_snapshot` is the authoritative rendering input for the deterministic perfect-information
  scope; runtime does not add a game-neutral board/view payload.
- Session status excludes runtime event lists — status stays lightweight and current-state
  oriented; event history lives in runtime transcripts.
- UI distinguishes runtime events from game-domain events by envelope location: runtime events are
  top-level `events` in the runtime transcript; game-domain events stay inside
  `match_transcript.turns[*].events`.
- Runtime event payloads self-identify with `event_scope="runtime"`.
- Payload stability is enforced with explicit full-payload tests plus version checks, not JSON
  Schema.

> Note: the RFC in §4 above proposes making `latest_snapshot` and `state_payload` per-seat. That
> would revise the second bullet here. Nothing has changed yet.

## Phase 23 — UI adapter boundary

`arena.ui` is a pure adapter over `arena.runtime` payloads and does not import simulation, game,
match, transport, persistence, or rendering code. It preserves `latest_snapshot` as the
authoritative state envelope and exposes `state_payload` as the snapshot's opaque state mapping for
board rendering. It does not recompute game rules.

Helpers: `build_match_status(...)`, `build_match_transcript(...)`, `build_match_screen(...)`.

## Phase 25 — abort path

`HumanQuit` inherits `BaseException` so it propagates past `step_session`'s `except Exception`
guard and reaches the driver. The driver catches both it and `KeyboardInterrupt` in inner and outer
handlers, calls `Arena.abort_session(...)` with `AbortReason.USER_QUIT` or
`AbortReason.USER_INTERRUPT`, and always writes both JSON files before returning.

## Phase 27 — protocol adversarial-review outcomes

Applied to `docs/NETWORK_PROTOCOL.md`:

- Full HTTP request/response shapes for `POST /matches`, `GET /matches/{id}`, `GET /games` (§4.1).
- `GET /schemas/payloads` (§17) serving JSON Schema for every payload type, so non-Python SDKs can
  codegen against one source of truth.
- §18 "Message broadcast matrix" disambiguating recipients per message type.
- `resume_token` scoped server-side to `(match_id, seat)` and rotated on every resume; mismatch
  closes `4401`.
- Match creation locks `per_turn_deadline_ms`, `per_action_retry_budget`, `disconnect_grace_ms`;
  `welcome` echoes them.
- Deterministic close ordering on retry-budget exhaustion: `action_rejected(0)` →
  `match_state(aborted)` → `match_aborted` → WS close `1000`.
- Atomicity rule for `running → finished/aborted`; "action arrives after terminal" rule.
- Per-connection FIFO + per-`turn_id` retry-counter decrement semantics.
- Per-match concurrent-connection cap (4) in §13 — **specified only; see Known Gaps**.
- Explicit v1 assumption: public-move perfect-information games only.
- "Byte-identical replay" replaced with "logically equivalent state".

## Phase 26 — local Ollama agents

`arena.cli.play.play_match` takes an optional `retry_sink`; after each `complete_turn` the driver
drains seat-keyed `(attempt, reason)` tuples written by agent callbacks and records them as
`PolicyRetried` runtime events. This keeps `arena.agents` ignorant of runtime internals.

`PolicyRetried` was added to the `RuntimeEvent` hierarchy additively — no `schema_version` bump.

## Phase 34 — deployment artifacts

`Dockerfile` (multi-stage `python:3.11-slim`, non-root user, `EXPOSE 8080`, `HEALTHCHECK` on
`/games`), `fly.toml` (shared-cpu-1x, 256MB, `auto_stop_machines = "stop"`,
`min_machines_running = 0`, `force_https = true`), `.dockerignore`, and `docs/DEPLOYMENT.md`
(Fly.io walkthrough plus a Caddy/VPS appendix).

`arena.agents.ollama.run_remote_seat` reaches `arena.sdk` transitively through
`arena.cli.remote.run_remote_seat_async` — the `arena.agents` → `arena.sdk` import is still
forbidden by `test_sdk_boundaries.py`, and no boundary change was needed.

TLS is always terminated by a reverse proxy, never by `arena.server` itself.

## Phase 35 — MCP layer

`SessionRegistry` holds a per-`(match_id, seat)` background `_recv_loop` feeding an asyncio.Queue.
Five tools: `join_match`, `get_observation`, `make_move`, `get_history`, `match_status`. HTTP/SSE
mode prints a loud stderr warning when bound to a non-localhost host, because there is no auth.

`arena.sdk` source was unchanged by this phase — the acceptance criterion.
