# AgentsArena Network Protocol

**Current wire `schema_version`: 4.** A server decodes versions 1-4, but serves only clients
that list 4 in `supported_schema_versions` (§7). Appendix A has the version history;
Appendix B the shapes and behaviour that earlier versions had.

This document is the language-agnostic source of truth for the wire protocol between agents and
an `arena.server` instance. Every implementation conforms to it: the server, the Python SDK
(`arena.sdk`), the TypeScript SDK (`sdk-ts/`), and the MCP wrapper. Where this document and an
implementation disagree, the implementation has a bug.

## 1. Scope

The protocol lets two agents play one match of a two-seat game, each over its own WebSocket,
while any number of spectators watch. A game may be sequential or simultaneous, deterministic or
stochastic (chance nodes), and have perfect or hidden information.

It reuses the simulation's payload shapes (`ObservationRequestPayload`, `ActionResponsePayload`,
`DomainErrorPayload`, runtime transcripts) verbatim; the wire adds an envelope. It is plain JSON,
so it can be debugged with `wscat` or browser devtools, and it is built to survive the network:
hung peers, malformed frames, duplicate sends, dead TCP sessions.

Out of scope: authentication beyond capability-by-`match_id`, lobby and matchmaking, more than
two seats, and running matches surviving a server restart (ended matches' public transcripts
can, §4.1).

## 2. Glossary

| Term | Definition |
|------|------------|
| **Player** | The human or organization that owns a seat. |
| **Agent** | The code that decides actions for a player (LLM, script, human via UI). |
| **Client** | The SDK instance and transport that connect an agent, or a spectator, to the server. |
| **Server** | An instance of `arena.server`. Authoritative for match state. |
| **Match** | One run of one game between two seats. Has an opaque `match_id`. |
| **Seat** | Integer identifier within a match: `0` or `1`. |
| **Viewer** | Whoever a payload is built for: a seat, or the public (a spectator). |
| **Turn** | One committed step: an **action** turn (one seat acted), a **chance** turn (a random outcome resolved; no seat), or a **joint** turn (several seats acted at once). |
| **Envelope** | The outer JSON object framing every WebSocket message: `{type, schema_version, ...}`. |

## 3. Transport

- **WebSocket, UTF-8 JSON text frames, one message per frame.** A binary frame closes the
  connection with `1003`; on a play channel that is a disconnect like any other, and the seat may
  resume (§11).
- **TLS.** The server speaks plain HTTP and WebSocket; a reverse proxy terminates TLS. Use
  `wss://` for anything but localhost. The seat URLs that `POST /matches` returns are `wss://`
  when the request came over https, or when the operator configured the server's public URL
  (`--public-url`, `docs/DEPLOYMENT.md`); otherwise `ws://` on the request's `Host`.
- **One connection per seat.** A client opens one play connection per seat it holds, and one
  spectate connection per match it watches.
- **Frame sizes.** The server accepts inbound frames of at most 1 MiB; every client message is
  small. Frames carrying a transcript (`match_finished`, `match_aborted`, a reconnect `welcome`,
  `spectator_welcome`) grow with the match: about 2 MB at the 5000-turn cap for a small game,
  more for a game with large states. Clients must accept frames of at least 16 MiB; the Python
  SDK accepts 64 MiB.
- **Compression.** The server does not negotiate permessage-deflate.
- **Keepalive.** The server sends protocol-level WebSocket pings every 20 s to every connection,
  spectators included, and closes one that does not answer within 20 s. This is separate from the
  application `ping` of §8.10, and WebSocket libraries answer it automatically, as long as their
  event loop is free.

## 4. Endpoints

| Method and path | Purpose |
|-----------------|---------|
| `POST /matches` | Create a match. |
| `GET /matches/{match_id}` | Match status. |
| `GET /matches/{match_id}/public-transcript` | The public transcript of an ended match. |
| `GET /games` | The games this server runs, with their config schemas. |
| `GET /schemas/payloads` | JSON Schemas of the payloads (§17). |
| `WS /matches/{match_id}/play?seat={0\|1}` | A seat's play channel. |
| `WS /matches/{match_id}/spectate` | A read-only spectator channel. |

Any other WebSocket path is accepted and closed `4404 unsupported_endpoint` (§9).

**The `match_id` is the capability.** It is unguessable (`secrets.token_urlsafe(16)`, at least
128 bits of entropy); whoever holds it can spectate, read the status and, once the match ends, the
public transcript, and, until both seats are claimed, take a seat. `GET /matches/{id}` exposes
player labels, lifecycle, whose turn it is, the turn count and the result: never the config or
game state.

### 4.1 HTTP request and response shapes

Every error response has the body `{"error": {"code": "...", "message": "..."}}`, plus
`"details"` where noted.

#### `POST /matches`

Request body (JSON; unknown keys are ignored):

```json
{
  "game_id": "connect4",
  "game_config": {"rows": 6, "columns": 7},
  "players": [{"label": "alice"}, {"label": "bob"}],
  "per_turn_deadline_ms": 30000,
  "per_action_retry_budget": 3,
  "disconnect_grace_ms": 30000,
  "supported_schema_versions": [4]
}
```

- `game_id` (required) must appear in `GET /games`.
- `game_config` (optional) must validate against the game's `config_schema`; omitted keys take
  their defaults.
- `players` (optional): at most 2 entries. Entry *i* labels seat *i* (its `player_id` is `p<i>`);
  a missing entry means that seat has no player record. A label is at most 64 characters; empty
  or null means no label.
- `per_turn_deadline_ms`: the wall-clock budget for answering an `observation_request`.
  1..600000, default 30000.
- `per_action_retry_budget`: rejected actions allowed per turn beyond the first. With budget *N*,
  a seat may be rejected *N* + 1 times; the last rejection carries `retries_remaining: 0` and
  aborts the match with `adapter_error` (§8.6). 0..10, default 3.
- `disconnect_grace_ms`: how long a dropped seat may take to resume (§11). 1..600000, default
  30000.
- `supported_schema_versions` (optional): the wire versions the creating client reads. If given
  without the server's version, creation fails with `400 schema_version_unsupported`; without it,
  a mismatch surfaces at `hello` as `4400`.

The per-IP creation cap (§13) is checked before the body is read.

Success, `201 Created`:

```json
{
  "match_id": "abc123...",
  "game_id": "connect4",
  "game_schema_version": 1,
  "schema_version": 4,
  "lifecycle": "created",
  "per_turn_deadline_ms": 30000,
  "per_action_retry_budget": 3,
  "disconnect_grace_ms": 30000,
  "seat_0_url": "wss://arena.example.com/matches/abc123.../play?seat=0",
  "seat_1_url": "wss://arena.example.com/matches/abc123.../play?seat=1"
}
```

Errors:

| Status | `code` | When |
|--------|--------|------|
| 400 | `unknown_game` | `game_id` is not registered. |
| 400 | `invalid_config` | `game_config` does not validate. `details` is the domain error's `details` object (often `{}`). |
| 400 | `invalid_request` | Not JSON, no `game_id`, a field of the wrong type, or a value out of range. |
| 400 | `schema_version_unsupported` | `supported_schema_versions` lacks the server's version. |
| 413 | `request_too_large` | Body over 64 KiB. |
| 429 | `rate_limited` | Per-IP creation cap (§13). |
| 503 | `server_busy` | The match registry is full of running matches (§13). |
| 500 | `server_error` | Internal failure. |

#### `GET /matches/{match_id}`

Success, `200`:

```json
{
  "match_id": "...",
  "game_id": "connect4",
  "lifecycle": "finished",
  "schema_version": 4,
  "current_seat": null,
  "acting_seats": null,
  "turn_count": 17,
  "players": [
    {"player_id": "p0", "label": "alice", "seat": 0},
    {"player_id": "p1", "label": "bob", "seat": 1}
  ],
  "result": {"result_type": "Win", "payload": {"seat": 0}},
  "abort": null
}
```

- `acting_seats` lists the seats that act now, and `current_seat` is that seat when exactly one
  acts; both are null unless the match is running.
- `result` is the result of a finished match (§17), null otherwise.
- `abort` is `{"reason": "...", "message": "..."}` for an aborted match, null otherwise.

Errors: `404 match_not_found`.

#### `GET /matches/{match_id}/public-transcript`

Success, `200`: the `RuntimeTranscriptPayload` (§17) of an ended match, **exactly the transcript
a spectator received** in `match_finished` or `match_aborted`. For a hidden-information game that
is the public view (`view: "public"`): no private state, no private event, and chance outcomes as
the public saw them. A perfect-information game's transcript is the full one (`view: "full"`).
Finished and aborted matches are both served.

Every response on this path, errors included, carries `Cache-Control: private, no-store`: the
URL is a capability.

The server keeps these transcripts in a store that outlives the WebSocket connections and the
registry. With a durable store (`docs/DEPLOYMENT.md`) they also outlive a restart. Only the public
transcript is stored or served; seat views are never available over HTTP. By default a transcript
is kept 7 days from the end of the match, at most 10,000 of them plus a byte cap, oldest dropped
first; one larger than the per-record cap (8 MiB durable, 4 MiB in memory) is not stored. At most
4 reads are served at once server-wide; further reads wait their turn.

Errors:

| Status | `code` | When |
|--------|--------|------|
| 404 | `match_not_found` | Unknown or malformed id, expired, or never stored (the store refused or failed). |
| 409 | `transcript_not_ready` | The match has not ended (including one that never started), or has just ended and its transcript is being stored. It is available once `match_finished` / `match_aborted` has been sent. |
| 429 | `rate_limited` | Per-IP read cap (§13). |

#### `GET /games`

Success, `200`:

```json
{
  "games": [
    {
      "game_id": "connect4",
      "game_schema_version": 1,
      "config_schema": {"type": "object", "properties": {"rows": {"type": "integer"}}},
      "min_seats": 2,
      "max_seats": 2
    }
  ]
}
```

One entry per registered game (the reference server runs `connect4`, `tictactoe`, `nim`, `pig`,
`liarsdice` and `rps`). `config_schema` is the JSON Schema of the game's config model; clients
may validate a config against it before `POST /matches`.

## 5. Lifecycle

```
created ── both seats joined ──► running ── result reached ──► finished
   │                               │
   │                               └── deadline / disconnect / budget / cap / crash ──► aborted
   └── never started: evicted after an hour idle; waiting clients closed 4410 match_expired
```

The lifecycle values are `created`, `running`, `finished` and `aborted`, as in the runtime
(`arena.runtime`). `match_state` (§8.3) is the only signal of a transition.

## 6. Envelope

Every WebSocket message is one JSON object:

```json
{
  "type": "action_response",
  "schema_version": 4,
  "match_id": "...",
  "seat": 0,
  "turn_id": "5f0c...",
  "payload": {
    "action_response": {"game_id": "connect4", "schema_version": 1, "seat": 0, "action": {"column": 3}}
  }
}
```

| Field | Rules |
|-------|-------|
| `type` | Always. One of the message types in §8. |
| `schema_version` | Always. The server stamps 4. A client should stamp the version it negotiated (4); the server accepts 1-4 here. |
| `match_id` | Set on every server frame. Optional and ignored on client frames. |
| `seat` | Set on `welcome`, `observation_request` and `action_rejected`; null on other server frames. Ignored on client frames. |
| `turn_id` | Set by the client on `action_response` (§12); echoed on `action_rejected`; null elsewhere. |
| `payload` | Always. A message-specific object; every message type has required fields. |

Server frames always carry all six keys, with null where a field does not apply.

**Unknown fields.** Unknown envelope keys, and unknown keys in a §8 message body, are ignored.
The payloads nested inside bodies, which are reused from the simulation (the `observation_request`
and `action_response` payloads, `DomainErrorPayload`, runtime and match transcripts, snapshots and
abort metadata), **reject unknown keys**: an `action_response` whose inner payload has an extra key
fails to decode. Adding a field there is therefore a version bump.

## 7. Versioning

- The wire `schema_version` covers the envelope and every payload shape, not game configs.
- It is bumped for removed, renamed or retyped fields, semantic changes, new required fields, and
  new fields in the nested payloads of §6 (they reject unknown keys).
- It is not bumped for new optional fields in §8 bodies, new message types that older clients can
  ignore, or additive enum values.

**Three version numbers ride the wire.** Only the first is negotiated:

| Number | Where | Current value |
|--------|-------|---------------|
| Wire `schema_version` | envelopes, `welcome`, runtime transcripts, `GET /schemas/payloads` | 4 |
| Adapter payload `schema_version` | inside `observation_request.observation_request` and `action_response.action_response` | 1 (a client sends 1) |
| Snapshot `schema_version` | inside every snapshot | 1 |

Each game also has a `game_schema_version` (currently always 1), returned by `GET /games`,
`POST /matches`, `welcome` and `spectator_welcome`. It versions that game's config and state
shapes, independently of the wire. Clients do not send it.

**Decode and emit are separate.** A server emits its own version but decodes every version it
can still read (1-4), so a fleet can migrate without a flag day.

**Negotiation is strict: a server serves only its own version.** It accepts a `hello`, a
reconnect `hello` or a `spectator_hello` **only if its version is in
`supported_schema_versions`**, and otherwise closes `4400 schema_version_mismatch`. A client
that cannot read the current version is refused rather than served an older shape; for a
hidden-information game an older shape could not be produced without leaking. A client should
list every version it reads: the Python SDK sends `[1, 2, 3, 4]`, the TypeScript SDK `[4]`.

## 8. Message types

Every message uses the envelope of §6. The sections below give `payload` shapes.

### 8.1 `hello` (client → server, the first frame on a play channel)

```json
{
  "client_name": "arena-sdk-python",
  "client_version": "0.1.0",
  "supported_schema_versions": [1, 2, 3, 4],
  "auth": null,
  "requested_seat": 0,
  "resume_token": null
}
```

- A client has 10 s from opening the socket to send it (`4422 hello_timeout`).
- `auth` is reserved; send `null`. Non-null values are ignored.
- `requested_seat` must equal the URL's `?seat=` on a fresh join (`4422 seat_mismatch`). A resume
  ignores it: the URL's seat decides.
- `resume_token`: `null` for a fresh join, or the token from this seat's latest `welcome` to
  resume (§11).

The server checks a `hello` in a fixed order; §9 gives it.

### 8.2 `welcome` (server → client, the answer to `hello`)

```json
{
  "match_id": "...",
  "game_id": "connect4",
  "game_schema_version": 1,
  "seat": 0,
  "lifecycle": "created",
  "schema_version": 4,
  "negotiated_schema_version": 4,
  "resume_token": "<opaque>",
  "per_turn_deadline_ms": 30000,
  "per_action_retry_budget": 3,
  "disconnect_grace_ms": 30000,
  "players": [
    {"player_id": "p0", "label": "alice", "seat": 0},
    {"player_id": "p1", "label": "bob", "seat": 1}
  ],
  "match_config": {"rows": 6, "columns": 7},
  "transcript": null
}
```

- `negotiated_schema_version` is the server's version (§7).
- `resume_token` is opaque, bound server-side to this match and seat, and **rotated on every
  `welcome`**, fresh or resumed: only the latest one works.
- `match_config` is the validated config **as this seat may see it**. Games keep secrets out of
  config (a seed there would be public), so in practice it is the whole config.
- `transcript` is null on a first join. On a resume it is this seat's runtime transcript so far
  (`view: "seat"`), holding exactly the turns the seat was sent live (§11).
- The deadline, budget and grace echo the values fixed at creation.

### 8.3 `match_state` (server → every seat and spectator)

```json
{
  "lifecycle": "running",
  "current_seat": 0,
  "acting_seats": [0],
  "turn_count": 0,
  "result": null,
  "abort": null
}
```

- `acting_seats` lists every seat that acts now: one in a sequential game, several in a
  simultaneous round (then `current_seat` is null). Both are null unless the match is running.
- `turn_count` counts committed turns, chance turns included.
- `result` is the result of a finished match (§17), null otherwise.
- `abort` is the full `AbortMetadataPayload` (§17) of an aborted match, null otherwise.

Sent when the match starts, after each step (one step can commit several turns: an action and
the chance turns it leads to; all their `turn_committed` frames come first), when the match
finishes, and when it aborts. A resuming seat is also sent one right after its `welcome`.

### 8.4 `observation_request` (server → an acting seat)

```json
{
  "observation_request": {
    "game_id": "connect4",
    "schema_version": 1,
    "seat": 0,
    "observation": {"seat": 0, "board": [[null, null]], "legal_actions": [{"column": 0}]}
  },
  "deadline_ms": 30000
}
```

- `observation_request` is the `ObservationRequestPayload` (§17): `observation` is the game's
  serialized observation for this seat, built for this seat only. The legal moves are inside it,
  in a game-specific shape.
- `deadline_ms` is the time left to answer. The deadline runs from when the request is sent; it
  is absolute: rejections and reconnects do not extend it. On expiry the match aborts with
  `turn_deadline_expired`. A re-sent request after a resume carries the remaining time (at least
  1).
- **One action per request.** A client sends one `action_response` per request, plus one per
  `action_rejected` while retries remain. The server reads a seat's frames only while it waits for
  that seat, so an extra action is not discarded: it is read as the answer to the next request.

**Simultaneous rounds.** When several seats act at once, each gets its own request at the same
time, none depending on another's choice, each with its own deadline, retry budget and
disconnect grace. The first seat to run out of any of them ends the match. A seat whose action is
accepted hears nothing more until the round commits; it is not told the other seat's action, or
whether it has acted.

### 8.5 `action_response` (client → server)

```json
{
  "action_response": {
    "game_id": "connect4",
    "schema_version": 1,
    "seat": 0,
    "action": {"column": 3}
  }
}
```

- The envelope's `turn_id` should be set, unique per attempt (a retry after `action_rejected`
  needs a new one). Without one the server assigns its own, and a duplicate cannot be detected.
- `action_response` is the `ActionResponsePayload` (§17). Its `schema_version` must be 1 and its
  `game_id` the match's game; otherwise the action is rejected with `adapter_error` and costs a
  retry. Its `seat` is informational: an action is always attributed to the connection's seat.
  `action` is a game-specific object.
- A legal action is committed. An illegal one is answered with `action_rejected`.

### 8.6 `action_rejected` (server → the seat whose action it was)

```json
{
  "turn_id": "5f0c...",
  "error": {"code": "illegal_action", "message": "Column 3 is full.", "details": {"column": 3}},
  "retries_remaining": 2
}
```

- `error` is a `DomainErrorPayload`: a domain code from the rules (`illegal_action`,
  `wrong_player`, `game_finished`, `serialization_error`, ...) with its `message` and `details`, or
  `adapter_error` when the action could not be loaded at all (wrong `game_id`, adapter
  `schema_version` other than 1, an action of the wrong shape).
- `retries_remaining` counts the further attempts allowed, reported **before** this rejection
  spends one: with budget 3 the rejections carry 3, 2, 1 and finally 0. The turn stays open and
  the deadline keeps running; no new `observation_request` is sent, so the client answers the same
  request again.
- A rejected `turn_id` is burned: resending it is silently dropped (§12).

**On the last rejection** (`retries_remaining: 0`) the match aborts. The seat receives, in this
order: this `action_rejected`, `match_state` with `lifecycle: "aborted"` (reason
`adapter_error`), `match_aborted` (§8.9), and a close `1000 adapter_error`. Frames sent after the
last rejection are never read.

### 8.7 `turn_committed` (server → every seat and spectator)

```json
{
  "turn_record": {
    "turn_index": 4,
    "kind": "action",
    "seat": 0,
    "action": {"column": 3},
    "outcome": null,
    "events": [{"event_type": "DiscDropped", "payload": {"seat": 0, "column": 3, "row": 5}}],
    "post_snapshot": {"game_id": "connect4", "schema_version": 1, "config": {}, "state": {}}
  },
  "post_snapshot": {"game_id": "connect4", "schema_version": 1, "config": {}, "state": {}},
  "public_snapshot": {"game_id": "connect4", "schema_version": 1, "config": {}, "state": {}},
  "events": [{"event_type": "DiscDropped", "payload": {"seat": 0, "column": 3, "row": 5}}]
}
```

Sent once per committed turn, to every seat and spectator, **each in its own view**:

- `turn_record` is the turn (§17). `turn_index` is 0-based and increases by one per turn; clients
  may deduplicate by it.
- `post_snapshot` (also inside `turn_record`) is the state after the turn in the recipient's view:
  its seat's for a seat, the public one for a spectator. `public_snapshot` is the public view,
  the same for everyone; for a perfect-information game it equals `post_snapshot`.
- `events` (also inside `turn_record`) are the game's domain events that the recipient may see. An
  event private to some seats (a dealt hand) carries `"is_public": false` and
  `"audience": [seats]` and reaches only them; a public event carries neither key.
- A chance turn (`kind: "chance"`) has null `seat` and `action`, and `outcome`: the random
  outcome as the recipient may see it (a spectator may get `{}` for a private deal). Nobody can
  recompute an outcome, so this and its events are how clients learn it.
- A joint turn (`kind: "joint"`, a simultaneous round) has null `seat` and `action`, and
  `actions`: every acting seat's action, keyed by the seat as a string (`"0"`, `"1"`). It is sent
  once the last acting seat's action is accepted, never before. Other turns have no `actions` key.

One accepted action can commit several turns: the action, then one chance turn per chance node
it leads to (the die roll after a Pig `roll`). A game that opens at a chance node sends those turns
before the first `match_state`.

### 8.8 `match_finished` (server → every seat and spectator)

```text
{
  "result": {"result_type": "Win", "payload": {"seat": 0}},
  "transcript": <RuntimeTranscriptPayload, §17>
}
```

- `result` is the result (§17): the same for every recipient.
- `transcript` is the recipient's runtime transcript (§17): `view: "seat"` for a seat of a
  hidden-information game, `"public"` for its spectators, `"full"` for everyone in a
  perfect-information game.

The last frame; the server then closes with `1000 normal_closure`.

### 8.9 `match_aborted` (server → every seat and spectator)

```text
{
  "abort": {"reason": "turn_deadline_expired", "message": "...", "cause_type": null, "cause_message": null},
  "transcript": <RuntimeTranscriptPayload, §17>
}
```

- `abort` is the `AbortMetadataPayload` (§17). `reason` is one of `turn_deadline_expired`,
  `peer_disconnected`, `heartbeat_timeout`, `adapter_error`, `turn_limit_exceeded`, `core_error`
  (the rules refused a simultaneous round) or `runtime_error` (the server's match driver failed).
  For a hidden-information game `cause_message` is always null.
- `transcript` is the recipient's runtime transcript, as for `match_finished`.

The last frame; the server then closes with `1000` and a reason naming the abort (§9.1), or
`4500 server_error` for `runtime_error`.

### 8.10 `ping` / `pong` (server → acting seat; client → server)

```json
{"nonce": "3f2a9c1e"}
```

The server pings an **acting seat while its turn is open** (in a simultaneous round, each acting
seat until its action is accepted); spectators and off-turn seats get no application pings. The
first ping goes 20 s after the `observation_request`; each later one 20 s after the previous pong
or miss. The client answers with `pong` echoing the `nonce`; a pong with another nonce is
ignored. A ping not answered within 20 s is a miss, and the second consecutive miss closes the
connection `4408 heartbeat_timeout`, about 80 s after the request. With the default 30 s turn
deadline, the deadline always fires first.

The server never answers a client's `ping`. A `4408` close is a disconnect: the grace period of
§11 applies, and if the seat does not resume the match aborts with `heartbeat_timeout`.

**After the end.** Once the server has sent `match_state` with a lifecycle other than `running`,
it reads nothing more from the seats: it sends the terminal frame and closes both play channels.
An `action_response` still in flight is never read. The code `match_already_finished` is reserved
and not emitted. The transition itself is atomic: a frame lands either before it (and is processed
normally) or after it (and is not read).

### 8.11 `error` (server → client)

```json
{"code": "malformed_envelope", "message": "..."}
```

On a play channel, sent to the acting seat for a frame the server could not use: one that is not
JSON or not a valid envelope, one with an envelope `schema_version` outside 1-4, or a message
type other than `action_response`, `pong` or `ping` during its turn. The connection stays open
and the error costs no retry, but a seat that sends 16 such frames in one turn is closed
`4422 too_many_malformed_frames` (§13).

On a spectate channel, a well-formed envelope of any type other than `ping`/`pong` is answered
with `error` code `protocol_violation`, and the connection is closed `1000 match_over`. A frame
that does not parse is ignored.

### 8.12 `spectator_hello` / `spectator_welcome`

`spectator_hello` (client → server), the first frame on a spectate channel, within 10 s of
opening it:

```json
{
  "client_name": "my-viewer",
  "client_version": "0.1.0",
  "supported_schema_versions": [4]
}
```

No seat and no resume token: a reconnecting spectator says hello again and gets fresh history.

`spectator_welcome` (server → client):

```json
{
  "match_id": "...",
  "game_id": "connect4",
  "game_schema_version": 1,
  "lifecycle": "running",
  "schema_version": 4,
  "negotiated_schema_version": 4,
  "players": [{"player_id": "p0", "label": "alice", "seat": 0}],
  "turn_count": 4,
  "transcript": null
}
```

- `transcript` is the public runtime transcript so far (the full one for a perfect-information
  game), and null before the match starts. A spectator joining mid-match can render at once; no
  other history message exists.
- Live frames follow: `match_state`, `turn_committed`, `match_finished`, `match_aborted`, never
  `observation_request` or `action_rejected`. A spectator is sent no `turn_committed` for a turn
  its welcome's transcript already carried, and misses none after it.
- If the match has already ended, the server sends `spectator_welcome`, whose transcript is the
  final one, and closes `1000 match_over`.

## 9. Errors

### 9.1 Close codes

| Code | Reasons | Meaning |
|------|---------|---------|
| `1000` | `normal_closure` | The match finished; `match_finished` was delivered. |
| `1000` | `turn_deadline_expired`, `peer_disconnected` (also after a heartbeat timeout), `adapter_error`, `turn_limit_exceeded`, `core_error`; `match_aborted` for an abort before the match started | The match aborted; `match_aborted` was delivered. |
| `1000` | `superseded` | A resume replaced this connection (§11). |
| `1000` | `match_over` | Spectator: the match has ended, or the spectator sent a message it may not. |
| `1000` | `spectator_too_slow` | Spectator: its outbound queue overflowed (§13). |
| `1003` | | A binary frame. |
| `1008` | | A non-integer `?seat=` (rejected before the handler, reason is a validation message). |
| `1013` | `outbox_overflow` | A seat stopped reading and its outbound queue overflowed; it may resume (§11). |
| `4400` | `schema_version_mismatch` | The server's version is not in `supported_schema_versions`. |
| `4401` | `unauthorized` | The resume token is the *other* seat's current token. |
| `4404` | `unsupported_endpoint` | No such WebSocket endpoint. |
| `4408` | `heartbeat_timeout` | Two consecutive missed pongs (§8.10). |
| `4409` | `seat_taken` | The seat has a live connection, or the match is running and the `hello` has no resume token. |
| `4409` | `match_not_started` | A resume token before both seats have joined; send a fresh `hello`. |
| `4410` | `match_not_found` | No such match. |
| `4410` | `match_expired` | The match was evicted (§13) while the client waited or said hello. |
| `4410` | `match_over` | The match has ended: no seat can be claimed or resumed. |
| `4410` | `invalid_resume_token` | A token that is not this seat's current one (rotated, from another match, or from before a restart). |
| `4422` | `invalid_seat` | `?seat=` missing or not 0 or 1. |
| `4422` | `hello_timeout`, `no_hello_received` | No `hello` / `spectator_hello` within 10 s, or the socket closed first. (A binary first frame closes `1003`.) |
| `4422` | `malformed_envelope`, `expected_hello_got_<type>`, `expected_spectator_hello_got_<type>` | The first frame is not a valid `hello` / `spectator_hello`. |
| `4422` | `seat_mismatch` | A fresh `hello`'s `requested_seat` differs from `?seat=`. |
| `4422` | `too_many_malformed_frames` | 16 unusable frames in one turn (§8.11). |
| `4429` | `connections_per_ip`, `connection_opens_per_ip`, `connections_per_match`, `spectators_per_match` | A rate cap (§13). |
| `4500` | `server_error` | Internal failure: the match driver crashed (the match aborts `runtime_error` first), or a `welcome` could not be sent. |

After the handshake, a malformed frame is answered in-band (§8.11) and does not close the
connection until the cap.

**Refusals before `hello`.** A connection refused before its `hello` is read (unknown endpoint,
unknown match, bad `?seat=`, a per-IP cap) is accepted, the server waits up to 1 s for the client's
first frame, and then closes with the code. A client should send its `hello` as soon as the socket
opens and expect the close code, not a refused handshake.

### 9.2 The order of checks on a play channel

1. Per-IP caps: `4429`.
2. The match exists: `4410 match_not_found`.
3. `?seat=` is 0 or 1: `4422 invalid_seat`.
4. Accept; the first frame arrives within 10 s and is a valid `hello`: `4422`.
5. The match still exists: `4410 match_expired`.
6. With a `resume_token`, the resume path: the match has not ended (`4410 match_over`); the token
   is the seat's current one (`4401` if it is the other seat's, else `4410
   invalid_resume_token`); the version is served (`4400`); the match is running (`4409
   match_not_started`).
7. Without one: the match has not ended (`4410 match_over`); it is not running (`4409
   seat_taken`); `requested_seat` matches (`4422 seat_mismatch`); the version is served (`4400`);
   the per-match cap (`4429`); the seat is free (`4409 seat_taken`).

A spectate channel checks the per-IP caps, the match, the first frame (`spectator_hello`), the
version, whether the match still exists, and the per-match spectator cap, in that order.

### 9.3 In-band error codes

| Code | Carried in | Meaning |
|------|------------|---------|
| a domain code (`illegal_action`, `wrong_player`, `game_finished`, `serialization_error`, ...) | `action_rejected.error` | The rules refused the action. The code, message and details are the domain error's own, never repackaged. |
| `adapter_error` | `action_rejected.error` | The action could not be loaded (§8.5). |
| `malformed_envelope` | `error` | An unusable frame from the acting seat (§8.11). |
| `protocol_violation` | `error` | A spectator sent a message other than `ping`/`pong`; the connection then closes. |
| `match_already_finished` | | Reserved; not emitted. |

## 10. Creating and joining a match

1. The creator sends `POST /matches` and receives the `match_id` and both seat URLs. The match is
   `created`.
2. Each player opens its seat URL and sends `hello`, and receives `welcome` with
   `lifecycle: "created"`. The creator hands the other seat's URL to its player out of band.
3. When the second `hello` is accepted the match starts. Any opening chance turns are sent as
   `turn_committed`, then `match_state` with `lifecycle: "running"` goes to both seats and every
   spectator, then an `observation_request` to each acting seat (seat 0 in a sequential game, both
   seats in a simultaneous round).
4. Turns proceed until `match_finished` or `match_aborted`.

Seats are assigned by URL; there is no seat negotiation.

## 11. Disconnects and reconnection

- **A drop is noticed when the server next reads the seat**: during its own turn, at once; for an
  off-turn seat, when its turn comes. Its `observation_request` is sent (and lost) first, so the
  turn deadline is already running.
- **Grace.** The seat then has `disconnect_grace_ms` to resume, capped by its turn deadline. If it
  resumes, play continues. If the deadline ends first the match aborts `turn_deadline_expired`;
  if the grace ends first, `peer_disconnected` (or `heartbeat_timeout` if a heartbeat closed it).
- **Both seats dropped.** No separate rule: the acting seat's grace or deadline decides.
- **Resume.** The client opens its seat URL again and sends `hello` with the `resume_token` from
  its latest `welcome`. The server answers with a `welcome` carrying a fresh token and
  **`transcript`: the seat's own transcript so far**, then a `match_state` to this seat, then, if
  the seat is acting and its action is not yet accepted, the `observation_request` again with the
  remaining `deadline_ms`. In a simultaneous round, a seat whose action was already accepted is not
  asked again. The client reaches the same state as one that never dropped: the framing differs,
  the information does not.
- **The resumed connection takes over at once.** An old socket still open (half-open TCP) is
  closed `1000 superseded`. The server builds the replay and swaps the connection into the
  broadcast set in one step, so every turn is either in `welcome.transcript` or sent live
  afterwards: never both, never neither.
- **A resume replays the seat's own view**, redacted like the live frames, so it learns nothing
  it would not have learned by staying connected.
- **Only a running match can be resumed.** Before both seats have joined, a token is refused
  `4409 match_not_started`; send a fresh `hello`.
- **A running match is reachable only by resume token.** A token-less `hello` for a running match
  is refused `4409 seat_taken`, even while a seat's grace period runs.
- **Nothing can be claimed or resumed after the end.** A `hello` for an ended match closes
  `4410 match_over`, and its tokens are invalid.
- **Server restart.** Running matches do not survive; a resume then closes `4410`.
- **Capability caveat.** Seat and spectate URLs share one `match_id`, so until both seats are
  claimed anyone who can spectate can take a seat. Share a hidden-information match's id only with
  its players until both have joined.

## 12. Idempotency and retries

- The server keeps, per seat, the `turn_id`s it has committed and rejected. An `action_response`
  whose `(seat, turn_id)` is among them is dropped silently: no reply, no retry spent, no commit.
  So a client must use a fresh `turn_id` for every attempt, a retry included, and never reuse one
  across turns.
- Frames on one connection are processed in arrival order. Only one connection per seat is live
  at a time (§11).
- The sets live in memory with the match.
- Broadcasts can be deduplicated by `turn_record.turn_index` (`turn_committed`) and `turn_count`
  (`match_state`).

## 13. Rate limits and resource bounds

Every cap below is enforced by the reference server (`arena/server/rate_limits.py`). A "source
IP" is the TCP peer, or the right-most entry of the operator's trusted client-address header
(`docs/DEPLOYMENT.md`); an IPv6 address counts by its /64, an IPv4-mapped one as its IPv4 address.

| Cap | Limit | On excess |
|-----|-------|-----------|
| Concurrent WebSocket connections per source IP | 8 | close `4429 connections_per_ip` |
| WebSocket opens per source IP per minute (seats and spectators; refused ones count) | 60 | close `4429 connection_opens_per_ip` |
| Match creations per source IP per minute (every attempt counts) | 5 | HTTP `429 rate_limited` |
| Concurrent seat connections per match | 4 | close `4429 connections_per_match` |
| Concurrent spectators per match | 16 | close `4429 spectators_per_match` |
| `action_response` frames read per match per second | 10 | throttled |
| Public-transcript reads per source IP per minute | 30 | HTTP `429 rate_limited` |
| Public-transcript reads served at once, server-wide | 4 | queued |

- **Per-match slots are claimed after a valid `hello`.** A resume with a valid token claims none
  and is never refused for the cap, so sockets that never said hello cannot lock a dropped seat out
  of its own reconnect. Spectators have their own cap for the same reason.
- **The action cap throttles, never closes.** The server delays reading the next action until the
  window has room. The delay is the server's: an action that has arrived counts as on time, and the
  wait is not charged to the deadline. The window is per match, so both seats of a simultaneous
  round share it. It counts only frames the server reads, which are the acting seats'.
- **Size bounds.** A create body is at most 64 KiB; `players` has at most 2 entries and a label at
  most 64 characters; an inbound frame at most 1 MiB.
- **Malformed frames.** At most 16 unusable frames per seat per turn, each answered with `error`;
  then `4422 too_many_malformed_frames`.
- **Slow readers.** A connection that falls 64 frames behind is closed: a spectator
  `1000 spectator_too_slow`, a seat `1013 outbox_overflow` (it may resume). A slow reader never
  slows the match.
- **Match length.** At most 5000 turns, chance turns included; then the match aborts
  `turn_limit_exceeded` (two Pig bots that only ever roll).
- **Registry.** At most 1000 matches. When full, a new match sheds finished matches first, then
  never-started ones, oldest first, and never a running match; if nothing can be shed, `POST
  /matches` returns `503 server_busy`. Ages count from a match's last change: a finished match is
  kept an hour after it ended, a never-started one an hour after creation, a running one 24 hours
  after its last turn. Eviction runs when a match is created, so these are minimums. Clients
  waiting on an evicted match are closed `4410 match_expired`.
- Other endpoints (`GET /matches/{id}`, `GET /games`, `GET /schemas/payloads`) are not
  rate-limited.

Rate limits bound abuse; they do not prevent it. The per-IP connection cap bounds how many sockets
one client can hold, and the malformed-frame cap how much logging one socket can cause.

## 14. Logging

The server writes one structured JSON log line per significant event, with at least:

```json
{"timestamp": "...", "level": "info", "event": "<event_name>", "match_id": "...", "seat": 0, "schema_version": 1}
```

Events include `match_created`, `match_started`, `seat_connected`, `seat_disconnected`,
`turn_committed`, `action_rejected`, `action_throttled`, `turn_deadline_expired`,
`turn_limit_exceeded`, `match_finished`, `match_aborted`, `heartbeat_timeout`,
`protocol_violation`, `rate_limited`, `spectator_connected`, `spectator_disconnected`,
`spectator_dropped`, `outbox_overflow`, `transcript_stored`, `transcript_not_stored`,
`transcript_store_failed`, `welcome_send_failed`, `run_match_error` and `public_view_failed`.
The `schema_version` field of a log line is the log format's version, 1.

Transcripts are never logged; they go to the transcript store.

## 15. Test contract (informative)

A conformant server passes, among others:

- a full match of every game, with two scripted clients and a spectator;
- illegal action → `action_rejected` → retry → commit; budget exhausted → `match_aborted`
  `adapter_error`;
- deadline expiry → `match_aborted` `turn_deadline_expired`;
- a mid-turn drop and resume within grace; a drop past grace → `peer_disconnected`;
- a duplicate `turn_id` → dropped, no double commit;
- a malformed frame → `error`, connection survives; a binary frame → close `1003`;
- a heartbeat miss → close `4408`;
- a simultaneous round: both seats asked at once, neither's action visible before the round
  commits;
- a hidden-information game: no seat or spectator receives anything it may not see.

The repository's `tests/integration/` runs these over real TCP, and
`tests/integration/test_typescript_sdk.py` runs the TypeScript SDK against the server.

## 16. Forward compatibility

- `hello.auth` is reserved, so token-based authentication can be added without a version bump.
- `resume_token` is opaque, so reconnection strategies can change without changing the wire.
- Game configs evolve independently: a new optional config field is a `game_schema_version`
  change for that game, not a wire change.
- Clients must ignore message types they do not know (§7), and fields they do not know in §8
  bodies (§6).

## 17. Payload reference

The bodies of §8 reuse the simulation's payload models verbatim. Their JSON Schemas are published
at `GET /schemas/payloads`:

```json
{
  "schema_version": 4,
  "schemas": {
    "ObservationRequestPayload": {},
    "ActionResponsePayload": {},
    "DomainErrorPayload": {},
    "RuntimeTranscriptPayload": {},
    "SessionStatusPayload": {},
    "RuntimeEventPayload": {},
    "PlayerRecordPayload": {},
    "AbortMetadataPayload": {},
    "Envelope": {}
  }
}
```

`Envelope` is a `oneOf` over the envelope of each message type except `spectator_hello` and
`spectator_welcome`. The document is byte-stable for a given `schema_version`: any change to it is
a version bump. The match transcript inside a runtime transcript is published only as an object;
its shape is below. Non-Python clients may generate bindings from these schemas; the Python SDK
uses its bundled models.

**Shapes** (the JSON Schemas are authoritative):

- **`ObservationRequestPayload`**: `{game_id, schema_version: 1, seat, observation}`.
  `observation` is the game's serialized observation for `seat`; legal moves live inside it.
- **`ActionResponsePayload`**: `{game_id, schema_version: 1, seat, action}`. `action` is a
  game-specific object, loaded by the game's serializer. Extra keys are rejected.
- **`DomainErrorPayload`**: `{code, message, details}`. `details` is an object or null.
- **Result**: `{result_type, payload}`: `{"result_type": "Win", "payload": {"seat": 0}}` or
  `{"result_type": "Draw", "payload": {}}`.
- **Snapshot**: `{game_id, schema_version: 1, config, state}`, the viewer's view of the config and
  state. A full snapshot rehydrates the game state.
- **Event**: `{event_type, payload}`, plus `is_public: false` and `audience: [seats]` for a private
  event.
- **Turn in `turn_committed`**: `{turn_index, kind, seat, action, outcome, events,
  post_snapshot}`, plus `actions` for a joint turn.
- **Turn in a match transcript**: `{kind, seat, action, outcome, events, result, post_snapshot}`,
  plus `actions` for a joint turn. Its index is its position in `turns`; `result` is the result
  after that turn (null until the end).
  - `kind: "action"`: `seat` and `action` set, `outcome` null.
  - `kind: "chance"`: `seat` and `action` null, `outcome` the recorded outcome (as the viewer may
    see it).
  - `kind: "joint"`: `seat`, `action` and `outcome` null, `actions` maps each acting seat (a
    string key, in seat order) to its action.
- **Match transcript**: `{game_id, schema_version, config, initial_snapshot, turns, view,
  viewer_seat}`. Only a `view: "full"` transcript can be replayed; replay applies recorded chance
  outcomes and never re-rolls, so it needs no seed. The seed appears nowhere.
- **`RuntimeTranscriptPayload`**: `{match_id, game_id, schema_version, lifecycle, players, events,
  abort, match_transcript, view, viewer_seat}`. `events` are runtime events.
- **`RuntimeEventPayload`**: `{event_scope: "runtime", event_type, payload}`.
- **`AbortMetadataPayload`**: `{reason, message, cause_type, cause_message}`.
- **`PlayerRecordPayload`**: `{player_id, seat, label}`.

**Consistency.** A runtime transcript or session status must also agree with itself, and the
reference implementation rejects one that does not:

- `lifecycle` is one of `created`, `running`, `finished`, `aborted`, and `abort` is present exactly
  when it is `aborted`;
- players have distinct seats and distinct `player_id`s;
- `viewer_seat` is a seat exactly when `view` is `"seat"`, and null otherwise;
- a transcript's `view` and `viewer_seat` equal those of the match transcript it wraps;
- in a view other than `"full"`, `abort.cause_message` is null.

## 18. Who receives what

| Server message | Acting seat | Other seat | Spectators |
|----------------|-------------|------------|------------|
| `welcome` | the seat that said `hello` | | no (`spectator_welcome`) |
| `spectator_welcome` | no | no | the spectator that said hello |
| `match_state` | yes | yes | yes |
| `observation_request` | yes, each acting seat its own | no | never |
| `action_rejected` | the seat whose action it was | no | never |
| `turn_committed` | yes, its view | yes, its view | yes, the public view |
| `match_finished` / `match_aborted` | yes, its transcript | yes, its transcript | yes, the public transcript |
| `ping` | while its turn is open | no | no |
| `error` | its own unusable frames | no (not read off-turn) | after a forbidden message |

- In a simultaneous round every acting seat is an acting seat above. A seat that has acted and
  waits receives nothing about the others' choices until the joint `turn_committed`.
- A seat that misses broadcasts while disconnected recovers them in its resume `welcome` (§11).
- An off-turn seat's frames are not read until its turn.

## Appendix A. Version history

| Version | Shipped in | What changed |
|---------|-----------|--------------|
| 1 | v1 (Phases 0-35) | The initial protocol. |
| 2 | Phase 37 | **Chance turns.** Transcript turns gained `kind` (`"action"`, `"chance"`) and `outcome`; `seat` and `action` became nullable, since nobody chooses a chance outcome. `turn_committed.events` became load-bearing: it used to be an empty list, harmless while every game was deterministic, but a chance outcome cannot be recomputed. Replay applies recorded outcomes and never re-rolls; the seed is never sent. |
| 3 | Phase 38 | **Per-viewer payloads**, so hidden-information games can be served. `turn_committed` carries the recipient's own `post_snapshot`, a new `public_snapshot`, and only the events and chance-outcome parts it may see; private events carry `is_public` / `audience`. Transcripts declare `view` and `viewer_seat`. `welcome.match_config` is the seat's view, and `welcome.transcript` replays the seat's history on resume. `POST /matches` accepts `supported_schema_versions`. New abort reason `turn_limit_exceeded`. For a perfect-information game every view is the full one. |
| 4 | Phase 41 | **Simultaneous moves.** Several seats can act at once, each with its own `observation_request`, deadline, retry budget and grace. A round commits as one joint turn: `kind: "joint"` with an `actions` map keyed by seat. `match_state` and `GET /matches/{id}` gain `acting_seats`, and `current_seat` is null while several seats act. A sequential turn has no `actions` key. |

## Appendix B. Superseded shapes and behaviour

A server decodes versions 1-3 (§7), and older clients or stored transcripts may still show these
shapes.

**Transcript turns.**

- v1: `{seat, action, events, result, post_snapshot}`; `seat` and `action` always set; no `kind`,
  no `outcome`.
- v2: added `kind` (`"action"` or `"chance"`) and `outcome`; `seat` and `action` nullable.
- v3: transcripts added `view` and `viewer_seat`. A transcript without them is a full one.
- v4: added `kind: "joint"` and `actions`.

**Messages.**

- v1-v2: `turn_committed` had no `public_snapshot`; events had no `is_public` / `audience`;
  `welcome.transcript` did not exist, and a resumed seat was not replayed its history.
- v1-v3: `match_state` and `GET /matches/{id}` had no `acting_seats`.
- v1 and v2 servers refused to serve any game that declared hidden information.

**Server behaviour changed without a version bump** (a client may meet the old behaviour on an
older server):

- Before Phase 36 the spectate URL closed `4404`; spectators arrived with `spectator_hello` /
  `spectator_welcome`, new message types, which §7 allows without a bump.
- Before Phase 38 the action cap closed the seat `4429` at 2 actions per second; it now throttles
  at 10.
- Before Phase 40 a seat whose socket had dropped could be claimed by any holder of the
  `match_id` sending a token-less `hello`; a running match now requires the resume token.
- Before Phase 42:
  - `match_finished.result` was always `{}`, and `match_state.result` and `GET /matches/{id}`
    `result` always null; read the final transcript turn's `result` on such a server.
  - A seat that stopped reading had frames dropped silently, instead of being closed `1013`.
  - Malformed frames were answered without limit.
  - Seat URLs were always `ws://`.
  - Refusals before `hello` closed at once, and some clients (Node) saw `1006` instead of the
    code.
