# Match / Arena Handoff

Cross-session handoff note. **Last updated 2026-09-25**: a current-state document. Historical
phase decisions are kept in the appendix.

## 1. Current state

**v1 (Phases 0-35) and the v2 roadmap (Phases 36-42) are complete.** Wire `schema_version` 4;
decoders accept 1-4. Every layer's import direction is enforced by architecture tests
(`docs/ADAPTER_BOUNDARIES.md` has the table).

| Layer | State |
|-------|-------|
| `arena.core` | Pure simulation abstractions: chance nodes, per-seat views, joint (simultaneous) turns |
| `arena.games.*` | Connect 4, Tic-Tac-Toe, Nim, Pig (chance), Liar's Dice (hidden information and chance), Rock-Paper-Scissors (simultaneous) |
| `arena.games.scaffold` | `--kind basic\|chance\|hidden\|simultaneous`; the working kinds generate a playable game, adapters and a contract test |
| `arena.match` | Immutable matches, turn records (action, chance, joint), per-viewer transcripts |
| `arena.adapters.*` | In-process payload contract; pure wire envelopes |
| `arena.runtime`, `arena.ui` | Deadline-free coordination and screen payloads, per viewer |
| `arena.cli`, `arena.agents.ollama` | Terminal play and replay; local Ollama agents for every game |
| `arena.server` | FastAPI + WebSocket: spectators, rate limits, deadlines, heartbeats, resume, per-viewer frames, public transcripts in memory / files / SQLite |
| `arena.sdk`, `sdk-ts/` | Python and TypeScript clients, both tested against the real server |
| `arena.mcp` | MCP wrapper over the SDK (stdio, HTTP/SSE) |

`docs/NETWORK_PROTOCOL.md` was consolidated at v4 in Phase 42, every claim checked against the
code; superseded v1-v3 shapes are in its appendices.

## 2. Known gaps

1. **Never deployed.** `fly.toml` still carries the placeholder `app = "arena-server"`; set
   `ARENA_PUBLIC_URL` when it gets a hostname.
2. **Not published.** Neither `agents-arena` (PyPI) nor `@agents-arena/sdk` (npm) is released, so
   joining a match still needs the repository.
3. **No license yet.** The owner has not chosen one; `sdk-ts/package.json` declares MIT as a
   placeholder. Add a `LICENSE` and the `license` field in `pyproject.toml` together.

## 3. Locked decisions (still binding)

- WebSocket only; JSON wire format; not configurable.
- Per-turn deadlines, heartbeats and rate limits live in `arena.server`; `arena.runtime` stays
  deadline-free.
- Match identity is `secrets.token_urlsafe(16)`; possession of the id is the only capability.
- Seats are assigned by URL; a running match's seat is reachable only with its resume token.
- Everything sent to a viewer is built for that viewer; only the server holds a
  hidden-information game's full transcript.
- A random seed never goes in config or state; the match owns the generator.
- Structured JSON logging only in `arena.server`; lower layers and the SDKs stay quiet.
- Wire and runtime payloads are at `schema_version` 4; an incompatible change bumps it, and
  `GET /schemas/payloads` is pinned per version by a golden file.
- `docs/NETWORK_PROTOCOL.md` is the language-agnostic source of truth; the SDKs are reference
  implementations.
- **New games register with each layer's adapter registry** rather than adding dispatch
  branches (`docs/ADDING_A_GAME.md`).

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

**Phase 39 is complete** (2026-09-24): Liar's Dice (`arena.games.liarsdice`), the first game
with hidden information and chance. Two Ollama agents finish matches locally and over the server,
and no client ever receives a hand it may not see (wire tests plus the demo's audit). The live CLI
renders from the human seat's view. Running real agents also found and fixed two SDK bugs:
`action_rejected` crashed clients, and a slow `choose()` froze the heartbeat.

**Phase 40 is complete** (2026-09-25). The public transcript of every ended match is stored
before its terminal frame goes out, and served at `GET /matches/{id}/public-transcript`. The store
is in memory by default; `--transcript-store file:DIR | sqlite:PATH` makes it outlive a restart.
Only the public view is stored. A pre-phase adversarial review found, and the phase fixed:
- a seat-hijack path that leaked a seat's hand after one reconnect;
- MCP clients reading each other's sessions;
- turn deadlines a seat could extend for ever;
- a driver crash from one malformed frame;
- eviction of running matches.

**Phase 41 is complete** (2026-09-25, wire `schema_version=4`): simultaneous moves as joint
turns, with Rock-Paper-Scissors as the exemplar. The server asks every acting seat at once,
each with its own deadline, retries and grace; the round commits as one `turn_committed`, and
no throw is visible to anyone before both are in. Adversarial review found a double-abort race
(fixed: one shielded abort) and cross-seat turn-id blocking (fixed: per-seat turn ids).

**Phase 42 is complete** (2026-09-25): a packaged TypeScript SDK (`sdk-ts/`), scaffold kinds that
generate working chance, hidden-information and simultaneous games, and the docs reconciled with
the shipped v4 contract. An audit of the protocol doc against the code found about 30 wrong
claims, and four places where the code, not the doc, was wrong: `result` was always empty, a seat
that stopped reading silently lost frames, malformed frames were answered without limit, and seat
URLs were always `ws://` behind TLS. All four were fixed in code. Review also found that a Node
client saw `1006` instead of close codes sent before `hello` (the server now reads the first frame
before closing), and that the hidden scaffold's contract never checked seat 0's `keep` (the suite
now accepts `reveals(state, action)`).

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
