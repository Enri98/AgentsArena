# RFC: Imperfect-Information Game Support (v2)

Status: Draft for owner review. No code attached.
Scope: protocol-bumping (`schema_version` 1 -> 2). v1 (Phases 0-35) shipped only
deterministic perfect-information sequential 2-player games.

## 1. Problem statement

AgentsArena v1 ships three games (`connect4`, `tictactoe`, `nim`) that share one
strong assumption: every seat sees the same state, and every move is publicly
observable. The wire protocol bakes this in -- `turn_committed` and
`match_finished` broadcast the **full** post-state snapshot and the **full**
runtime transcript to both seats verbatim (`runtime_bridge.py:228-248`,
`runtime_bridge.py:251-262`). That blocks an entire class of games where
information asymmetry is the *point*: Liar's Dice, simplified Poker, Battleship,
Stratego, Coup, Resistance. These games are the natural next step for an LLM
arena because they reward modelling the opponent rather than just searching a
public game tree. This RFC proposes the smallest contract+wire change needed to
support them, with a single exemplar game (selected in section 6) to prove the
contract before opening the door to a wider catalog.

## 2. Current state

### 2.1 Observation today

`Observation` (src/arena/core/observations.py:10-20) is a frozen dataclass with
only a `seat: Seat` field plus a derived `observation_type` property.
Concrete games subclass it: `TicTacToeObservation`
(src/arena/games/tictactoe/observation.py:13-19) carries the **full board**,
`current_seat`, and that seat's `legal_actions`. Connect 4 follows the same
shape. In both cases the observation is "public state plus the requester's
seat label" -- which is exactly correct *only* because v1 games are
perfect-information.

`RulesEngine.observation(state, seat) -> Observation` is already per-seat by
signature (src/arena/core/rules_engine.py:66-67), but no current game uses the
`seat` argument to redact anything. The contract is *capable* of supporting
private views; the implementations just never exercised it.

### 2.2 Snapshots vs observations on the wire

The split is sharper than it looks. There are two distinct data flows:

- **`ObservationRequestPayload`**
  (src/arena/adapters/in_process.py:29-37, built by `build_observation_request`
  at line 99-111) carries `serializer.dump_observation(rules_engine.observation(state, seat))`.
  This is per-seat by construction. `obs_request` is sent **only** to the
  active seat as `observation_request` (runtime_bridge.py:616-627; protocol
  §8.4 and §18 broadcast matrix).
- **`turn_committed.post_snapshot`** carries `serializer.dump_state(state)` --
  the full authoritative state. It is broadcast to **both** seats
  (runtime_bridge.py:229-248, body model `TurnCommittedBody` at
  adapters/websocket/messages.py:144-151). The CLI/UI uses
  `latest_snapshot.state` directly as the rendering input
  (ui/payloads.py:308-318, "Phase 21 decision: `latest_snapshot` is the
  authoritative rendering input").
- **`match_finished.transcript`** and **`match_aborted.transcript`** include
  the full runtime transcript -- every turn's `post_snapshot`, every domain
  event -- also broadcast to both seats (messages.py:159-175, runtime_bridge.py:251-282).
- Reconnect resume replays the full transcript to the reconnecting seat
  (NETWORK_PROTOCOL.md §11), and that section already calls out the v1
  assumption: "Games with private state ... require a v2 extension that scopes
  transcript replay per-seat."

So the **observation pipeline is already per-seat**; the **snapshot pipeline is
shared, full-state, and load-bearing for rendering, replay, and reconnect**.
That is the incompatibility.

### 2.3 Why this blocks hidden info

A game like Liar's Dice produces a `state` containing both players' private
dice. v1's `Serializer.dump_state` returns one JSON object; the wire
broadcasts that object to both seats; one seat learns the other's hand.
There is no v1 path to scope the broadcast per-seat without changing the
contract. Lower layers compound the issue: the UI payload contract
(ui/payloads.py:155-162, `UIMatchScreenPayload`) assumes one
`latest_snapshot` per match; transcripts are also single-stream
(runtime/payloads.py around line 100, runtime_bridge.py:256). Three layers
each assume "one state, broadcast to all seats."

## 3. Proposed contract changes

The smallest cut: keep the simulation core's notion of state authoritative and
private to the server; promote `Observation` to the sole boundary that crosses
the per-seat wire; and add explicit metadata distinguishing public state from
private state for tooling, spectators, and replay redaction.

### 3.1 `Observation` (src/arena/core/observations.py)

No structural change required. Concrete games' observation subclasses become
the truth: they MUST contain only what `seat` is entitled to see. The base
class stays a frozen dataclass with `seat` and `observation_type`.

### 3.2 `RulesEngine` (src/arena/core/rules_engine.py)

`observation(state, seat) -> Observation` already covers per-seat redaction.
Add **one** optional method, defaulted in a thin mixin so existing engines
need no change:

- `public_state(state) -> Observation | PublicView` -- for the spectator path
  and for replay redaction. Returns the strictly-public view (no seat
  attribution). Default implementation for perfect-information games returns
  `observation(state, seat=0)` (any seat suffices when all are equal); games
  declaring `has_hidden_information=True` MUST override it.

### 3.3 `Serializer` (src/arena/core/serializer.py)

- Keep `dump_state` / `load_state` exactly as-is. They remain the
  **authoritative** server-side representation used by `LocalMatch` and by
  reconnect replay on the server.
- Add `dump_public_state(state) -> JSONMapping` and `load_public_state` -- the
  spectator-safe view derived from `public_state`. Perfect-info games default
  it to `dump_state`. Hidden-info games implement the redaction.
- `dump_observation` / `load_observation` are unchanged in signature but their
  contract is tightened: payload MUST contain no data the receiving seat is
  not entitled to see. This is the test contract that Phase 4-style harness
  enforces in 7.2.

### 3.4 `GameDefinition` (src/arena/core/game_definition.py)

Two additive fields, both with safe defaults so the three existing games stay
declaratively perfect-information:

- `has_hidden_information: bool = False`
- `public_state_type: type | None = None` -- the in-memory type returned by
  `RulesEngine.public_state`; `None` for perfect-info games.

The registry's duplicate-id check and architecture tests stay unchanged.

## 4. Proposed wire-protocol changes

This is a `schema_version=1 -> schema_version=2` bump. See §7 of
NETWORK_PROTOCOL.md for the existing version policy -- this change qualifies
as a semantic change to existing fields (`turn_committed.post_snapshot`,
`match_finished.transcript`).

### 4.1 Per-seat broadcasts

Today `turn_committed` (§8.7) broadcasts identical bytes to both seats.
v2 changes the **server** so that, for any game with
`GameDefinition.has_hidden_information=True`:

- `turn_committed.post_snapshot` is computed **once per seat** via
  `serializer.dump_state_for_seat(state, seat)` (a new serializer method --
  default: `dump_state` for perfect-info, redacted view for hidden-info), and
  sent only to that seat. Equivalently expressed as
  `dump_observation(rules_engine.observation(state, seat))` embedded in a
  snapshot envelope -- the spec should pick one canonical shape, with
  observation-as-snapshot being the cleaner choice.
- A new optional `turn_committed.public_snapshot` field carries the
  `dump_public_state` view, for v2 spectators (see §4.4 below) and for client
  rendering of public history.
- `turn_committed.events` continues to broadcast game-domain events, but
  hidden-info games MUST scope which events carry private fields. The
  RulesEngine event taxonomy adds an `is_public: bool` marker; the server
  filters non-public events to the seat(s) entitled to see them.

For perfect-info games the v2 server emits the same bytes both seats receive
today, plus the (identical) `public_snapshot`. v1 games keep working over
schema_version=2 with no behavior change.

### 4.2 `match_finished` and `match_aborted`

The full transcript is no longer broadcast verbatim to both seats. The v2
server emits two parallel transcripts -- a per-seat redacted transcript over
the play channel, and a public transcript over the spectate channel (§4.4).
Concretely, `match_finished.transcript` becomes the **seat-scoped**
transcript: each turn's `post_snapshot` is what that seat saw at the time;
each turn's `events` excludes events the seat was not entitled to.
`dump_runtime_transcript(session, seat=...)` is the obvious refactor target;
the existing single-arg form remains for in-process callers (e.g. the
runtime tests and JSON file dumps).

### 4.3 Backward compatibility

- Existing perfect-info games (`connect4`, `tictactoe`, `nim`) continue to
  work unchanged. Their `GameDefinition.has_hidden_information` defaults to
  `False`; their per-seat transcripts are byte-identical to the v1 shared
  transcript.
- v1 clients connecting to a v2 server: §7 negotiation kicks in. v2 servers
  publish `supported_schema_versions=[1, 2]`. A v1 client requesting
  `[1]` connects to a v1-shaped channel; v2-only games (those with
  `has_hidden_information=True`) refuse a v1 client at `POST /matches` time
  with `HTTP 400 invalid_config`. The narrower alternative -- forcing the
  whole ecosystem to v2 -- is rejected because the SDK ecosystem (incl. the
  MCP wrapper and any future TS SDK) is easier to migrate incrementally.
- v2 clients on a v1 server: the v1 server only advertises
  `supported_schema_versions=[1]`; negotiation closes with `4400`. v2 clients
  must downgrade or refuse.

### 4.4 Spectator role

Yes, this RFC is the right time to define `WS /matches/{id}/spectate`. The
endpoint is already reserved in v1 (NETWORK_PROTOCOL.md §4, closes `4404`).
In v2:

- Spectators send `hello` with no `requested_seat`. Server responds with
  `welcome` (`seat=null`, no `resume_token`).
- Spectators receive `match_state`, `turn_committed`, `match_finished`,
  `match_aborted`, `ping`/`pong`, `error` -- everything in the broadcast
  matrix EXCEPT `observation_request` and `action_rejected`.
- Spectator `turn_committed` carries `public_snapshot` (the
  `dump_public_state` view) instead of `post_snapshot`. Spectator transcripts
  are the public transcript.
- No reconnect grace for spectators; they may reconnect with a fresh `hello`
  and the server replays the public transcript.

Defining spectator alongside imperfect-info is cheaper than two protocol
bumps -- the public-view machinery is the same machinery.

## 5. Runtime / UI / MCP / SDK / CLI / agents impact

**`arena.runtime`.** `MatchSession` and `Arena` stay state-authoritative.
`dump_runtime_transcript` gains an optional `seat` parameter; the no-arg form
returns the public transcript (for tests/examples that dump to JSON).
`latest_snapshot` on `SessionStatusPayload` keeps meaning "full state" because
it is server-internal. A new optional `latest_observations: dict[seat ->
ObservationPayload]` field is the per-seat boundary. Runtime stays
deadline-free.

**`arena.ui`.** `UIMatchStatusPayload.latest_snapshot` and `state_payload`
become per-seat: `build_match_status(status_payload, *, seat=None)` -- with
`seat=None` meaning public view. The UI adapter performs no redaction itself;
it consumes whichever payload the server (or local runtime) hands it. The
CLI replay viewer keeps working against JSON dumps because the JSON dumps are
now seat-scoped or public-scoped at write time.

**`arena.sdk`.** Two cosmetic API touch-ups: `Session.observation` already
returns the seat's observation -- unchanged. `Session.history` (if it
exists, or its equivalent) returns the seat-scoped transcript. Per-game
schemas in `arena.sdk` add the new game's action shapes. `LocalSession`
helper keeps its in-process shortcut; it must call the seat-scoped serializer
to stay honest.

**`arena.mcp`.** The five tools (`join_match`, `get_observation`, `make_move`,
`get_history`, `match_status`) stay; `get_history` and `match_status` switch
to the seat-scoped views. Per-game JSON schemas (mcp/schemas.py) add the new
game.

**`arena.cli`.** The terminal replay viewer (`python -m arena.cli`) and the
interactive driver (`python -m arena.cli.play`) need a per-seat lens for
hidden-info games. The cleanest cut: render only the active seat's
observation when in `play` mode (where there is a single human anyway); in
replay mode, accept a `--seat N` flag selecting which transcript to render,
defaulting to the public transcript when available. Connect 4 / Tic-Tac-Toe /
Nim are unaffected because all four payloads (public + both seats) are
identical for perfect-info games.

**`arena.agents.ollama`.** Prompt builders already take an observation, not a
state (per arena/agents/ollama/prompts -- whatever the existing layout is).
The change is one line of guidance in the prompt builder docs: builders MUST
serialize ONLY the observation. The existing Connect4/TicTacToe builders
already meet this; the new game's builder is the test.

## 6. Exemplar game proposal

Three candidates surveyed:

- **Liar's Dice (simplified, 2-player, 5 dice each).** Pros: textbook
  imperfect-info game; small action space ("bid quantity/face" or "call");
  state and bids are both compact; the deception/bluff structure is exactly
  what LLMs are interesting at. Cons: requires randomness at deal time
  (per-match initial dice roll), which crosses into stochasticity. We can
  scope by making the dice roll a single per-match event at `initial_state`
  time -- still deterministic given the config's RNG seed.
- **Battleship.** Pros: simple action space (target a cell); state is
  literally two boards, one per seat, with ships hidden. Cons: ship placement
  phase is a multi-step pre-game; the contract change to support multi-phase
  setup is bigger than the contract change we are scoping; without
  randomness, ship placement must be supplied as config (boring) or
  randomized (stochastic). Also makes a poor LLM game -- early-game is just
  random guessing.
- **Coup-lite / Resistance-lite.** Pros: pure private-role deduction; LLM-strong.
  Cons: substantially more rules (action/counteraction/challenge cycle in
  Coup; per-mission voting in Resistance); 3+ player games are the natural
  shape and we are still 2-seat in v2 scope.

**Pick: Liar's Dice (simplified).** Smallest action space, smallest rule book,
no multi-phase setup, no extra player. The one stochastic concession -- a
seeded per-match dice roll at `initial_state` -- is local to the rules
engine, fits inside `Connect4Config`-style validation, and does not require
chance-node infrastructure on the wire because the roll happens before any
turn. It genuinely exercises the imperfect-info contract: each seat's
observation shows only its own dice and the bid history; the public state
shows only the bid history. Liar's Dice is the smallest test that fails on
v1 contracts and passes on v2 contracts.

## 7. Phased rollout

Five phases, ordered so each leaves the repo green.

### Phase 36 -- Contract additions, perfect-info still

Scope: add `GameDefinition.has_hidden_information`, `public_state_type`;
add `RulesEngine.public_state` default mixin; add
`Serializer.dump_public_state` / `load_public_state` defaults; tighten the
generic test contract (arena.testing.contracts) to enforce
"observation contains no data outside the seat's entitlement" for any game
declaring `has_hidden_information=True`. No game changes; no wire change.
Deliverables: `src/arena/core/game_definition.py`, `src/arena/core/rules_engine.py`,
`src/arena/core/serializer.py`, `src/arena/testing/contracts.py`, focused unit tests.
Verifiable: all v1 games still pass the contract suite unchanged; the
declared flag round-trips through registry and serializer.

### Phase 37 -- Liar's Dice game (perfect-info-shaped wire)

Scope: implement `arena.games.liarsdice` in full -- config (dice count, faces,
RNG seed), state (per-seat dice, current bid, current bidder), action
(`Bid(quantity, face)` or `Call`), observation, events, rules, serializer,
definition. `has_hidden_information=True`. Initially served over schema_version=1
via the existing pipeline: the server's `turn_committed.post_snapshot` will
leak dice; that is intentional for this phase -- we want the failing test
that documents the bug. Wire it through the runtime/UI in the same way
existing games are wired.
Deliverables: full vertical slice under `src/arena/games/liarsdice/`,
`tests/unit/games/liarsdice/`, a failing
`tests/integration/test_liarsdice_information_leak.py` that asserts
seat 0's `post_snapshot` does NOT contain seat 1's dice (red on main).
Verifiable: every other test passes; the new red test is the single failing
case and it is the precise contract being fixed in Phase 38.

### Phase 38 -- Wire schema_version=2

Scope: bump `arena.adapters.websocket.WIRE_SCHEMA_VERSION` to `2`. Extend the
server to compute per-seat `post_snapshot` for hidden-info games and emit
parallel public snapshots. Refactor `dump_runtime_transcript` to accept a
`seat` parameter; emit per-seat transcripts in `match_finished` /
`match_aborted`. Refactor `MatchFinishedBody` /
`TurnCommittedBody` to allow per-seat differences. Update SDK to negotiate
both `[1, 2]`. Update MCP wrapper to consume the seat-scoped transcript.
Architecture tests still enforce the layering. NETWORK_PROTOCOL.md gets a
v2 appendix; existing wording stays for v1 references.
Deliverables: `src/arena/adapters/websocket/`, `src/arena/server/runtime_bridge.py`,
`src/arena/server/routes_ws.py`, `src/arena/sdk/`, `src/arena/mcp/`,
`docs/NETWORK_PROTOCOL_v2.md` (or in-place update), reconnect tests.
Verifiable: the red test from Phase 37 turns green; all v1 game tests still
pass; new integration tests cover both seats' transcripts on a Liar's Dice
match; reconnect replays the seat-scoped transcript.

### Phase 39 -- Spectator endpoint

Scope: implement `WS /matches/{id}/spectate`. Server emits public snapshots
and public transcripts. SDK adds `connect_spectator(url)`. CLI gets
`--spectate` mode. Per-IP cap (`max_concurrent_connections_per_ip`) adjusts
to allow N>2 viewers per match.
Deliverables: `src/arena/server/routes_ws.py`, `src/arena/sdk/`,
`src/arena/cli/spectate/` (or equivalent), spectator integration tests
exercising Liar's Dice and Connect 4 head-to-head.
Verifiable: a third client can attach to a running match, sees only the
public view, never observes private dice; existing 2-seat flows unchanged.

### Phase 40 -- Documentation, replay tooling, README

Scope: update `IMPLEMENTATION_PLAN.md` Phases 36-39, `CLAUDE.md` layer
table (no new packages, just expanded contract), `docs/ADAPTER_BOUNDARIES.md`,
`docs/MATCH_ARENA_HANDOFF.md`, README "Watch two LLMs play remotely"
section. Add `examples/run_liarsdice_demo.py` mirroring
`examples/run_remote_demo.py`. Confirm Ollama prompt builders for Liar's
Dice work end-to-end.
Deliverables: docs only + one example + one Ollama prompt builder.
Verifiable: a Connect 4 demo, a Tic-Tac-Toe demo, a Liar's Dice demo all run
locally to completion; docs are consistent with the shipped code.

## 8. Open questions for the owner

1. **Stochasticity scope.** Liar's Dice needs a per-match dice roll. Do we
   accept that as an isolated stochastic-at-init event (small precedent), or
   do we defer Liar's Dice until we have a real chance-node primitive in
   v3? My recommendation: accept it as init-time randomness with a seeded
   RNG, gated to `initial_state` only. But this is your call.
2. **Spectator timing.** Spectator support is cheap *now* because the public
   view machinery is being built anyway. Do you want it landing in the same
   protocol bump (Phase 39) or as a v3 follow-on?
3. **TS SDK ordering.** Should we port the SDK to TypeScript *before* the
   v2 bump, so the wire migration only happens once? Cost: delays imperfect-
   info by one mid-sized phase. Benefit: avoids paying the wire-migration
   tax twice.
4. **N-player.** Liar's Dice in the wild is 4-8 players. v1 hardcodes
   `min_seats=max_seats=2`. Do we keep 2-seat for Phase 37, or combine the
   N-player change into the same protocol bump? My recommendation: keep
   2-seat for v2; the seat-broadcast changes are orthogonal to N>2 and N>2
   ripples through the runtime, server, SDK, MCP, and CLI.
5. **Simultaneous moves.** Some imperfect-info games (Rock-Paper-Scissors,
   sealed-bid auctions) are simultaneous. v2 stays strictly sequential.
   Confirm?
6. **Reconnect on hidden-info.** With per-seat transcripts, a reconnecting
   seat replays its own scoped history. Do we need any new test machinery
   to assert *no information added* across the disconnect boundary?
7. **Public-transcript distribution.** Should the public transcript be
   accessible via HTTP GET (e.g. `GET /matches/{id}/public-transcript`)
   for non-WebSocket consumers, or strictly via the spectate WS?

## 9. Out of scope for this RFC

This RFC does NOT cover:

- **Stochastic games beyond init-time randomness** (chance nodes mid-game,
  card draws, dice rolls inside turns). Separate concern; either v3 or a
  bounded extension to v2 to be argued separately.
- **N-player games (N != 2).** Independent decision; touches seat
  enumeration, scoring, and the broadcast matrix.
- **Simultaneous-move games.** v3 concern; needs a multi-pending-action
  variant of the turn loop.
- **Real authentication, tokens, or accounts.** Still v2 backlog per
  CLAUDE.md.
- **Third-party game registration.** Still v2 backlog.
- **Web spectator UI.** v2 reserves the URL and the protocol for spectators
  in Phase 39; the actual UI is web-spectator-UI work and stays deferred.
- **Persistence beyond JSON file dumps.** Unchanged.
- **Prometheus / OpenTelemetry.** Unchanged.
