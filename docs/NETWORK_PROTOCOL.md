# AgentsArena Network Protocol

Current wire `schema_version`: **3** (Phase 38). Versions 1-3 are all accepted on decode, but a
client must list 3 in `supported_schema_versions` to be served; see §7.1 for what changed.

This document is the language-agnostic source of truth for the wire protocol that connects remote
agents to an `arena.server` instance. Every implementation — the reference Python SDK, future
TypeScript SDK, MCP wrapper, and the server itself — must conform to it.

## 1. Goals and non-goals

### 1.1 Goals
- Let two remote agents play one match of a deterministic perfect-information game over a single
  WebSocket connection per agent.
- Reuse the existing `arena.core` payload shapes (`ObservationRequestPayload`,
  `ActionResponsePayload`, `DomainErrorPayload`) verbatim — the wire only adds an envelope.
- Be debuggable with `wscat`, browser devtools, and plain JSON.
- Tolerate the failure modes that appear the moment you cross the network: hung peers, malformed
  payloads, duplicate sends, dead TCP sessions, server restarts.

### 1.2 Non-goals (v1)
- Multiple simultaneous agents per connection
- ~~Spectator streams~~ — shipped in Phase 36; see §4 and §8.13
- Authentication beyond capability-by-match-id
- Persistence across server restarts
- Lobby / matchmaking / tournaments
- Reconnection with state-versioning conflict resolution beyond resume-from-turn-N

## 2. Glossary

| Term | Definition |
|------|------------|
| **Player** | The human or organization that owns a seat. Identity-level concept. |
| **Agent** | The code that decides actions for a player (LLM, script, human via UI). |
| **Client** | The SDK instance + transport that connects an Agent to the server. |
| **Server** | An instance of `arena.server`. Authoritative for match state. |
| **Match** | One run of one game between two seats. Has an opaque `match_id`. |
| **Seat** | Integer identifier (`0` or `1` for two-player games) within a Match. |
| **Envelope** | The outer JSON object framing every WS message: `{type, schema_version, ...}`. |

The term **Peer** is reserved for protocol-internal documentation and must not appear in user-facing
SDK or server APIs.

## 3. Transport

- WebSocket only. Plain `ws://` permitted on localhost; `wss://` required for non-loopback hosts.
- TLS termination is the deployer's responsibility (typically a reverse proxy such as Caddy or
  nginx in front of `arena.server`). The server itself speaks plain WebSocket.
- Each Client opens exactly one WebSocket connection per match-seat binding.
- Wire format: UTF-8 JSON text frames. Binary frames must be rejected with close code `1003`
  (unsupported data). On a play channel this is a disconnect like any other: the grace period
  of §11 applies and the seat may resume.
- One JSON message per WebSocket frame. No newline framing inside a frame.
- **Frame sizes.** The server accepts inbound frames of at most 1 MiB; every client message is
  small. Server frames carrying a transcript (`match_finished`, `match_aborted`, a reconnect
  `welcome`, `spectator_welcome`) grow with the match, to about 2 MB at the server's 5000-turn
  cap. Clients must accept frames of at least 16 MiB; the Python SDK accepts 64 MiB.
- **Keepalive.** The server sends protocol-level WebSocket pings every 20 s to every
  connection, spectators included, and closes one that does not answer within 20 s. This is
  separate from the application `ping` of §8.10, and WebSocket libraries answer it
  automatically.

## 4. URL shape

- `POST /matches` — create a match (HTTP).
- `GET /matches/{match_id}` — match status (HTTP, JSON, no auth).
- `GET /matches/{match_id}/public-transcript` — the public transcript of an ended match (HTTP,
  JSON, no auth; Phase 40).
- `GET /games` — list of supported game ids and their config schemas (HTTP, JSON).
- `WS /matches/{match_id}/play?seat={0|1}` — primary play channel (WebSocket).
- `WS /matches/{match_id}/spectate` — read-only spectator channel (WebSocket). Live as of
  Phase 36. The client opens it, sends `spectator_hello`, and receives `spectator_welcome`
  followed by the same broadcasts the seats receive, minus `observation_request` and
  `action_rejected`. No seat, no `resume_token`, and no disconnect grace: a reconnecting
  spectator simply says hello again and gets fresh history.

The unguessable `match_id` (>=128 bits of entropy via `secrets.token_urlsafe(16)`) is the
capability. Possession of the URL grants the right to join the match.

> **Information exposed by `GET /matches/{match_id}`:** player labels, lifecycle, whose turn it is,
> and the turn count, to any holder of the `match_id`. It does **not** expose `match_config` or any
> game state. For the capability-by-id trust model this is by design.

### 4.1 HTTP request and response shapes

#### `POST /matches`

Request body (JSON):

```json
{
  "game_id": "connect4",
  "game_config": { ... },
  "players": [
    {"label": "alice"},
    {"label": "bob"}
  ],
  "per_turn_deadline_ms": 30000,
  "per_action_retry_budget": 3,
  "disconnect_grace_ms": 30000,
  "supported_schema_versions": [3]
}
```

- `game_id` must appear in `GET /games`.
- `supported_schema_versions` (optional, v3) lists the wire versions the creating client reads. If
  it is given and does not include the server's version, creation fails with `400`
  `schema_version_unsupported`. Without it the mismatch surfaces later, at `hello`, as `4400`.
- `game_config` must validate against the registered serializer's config schema.
- `players` length must equal the seat count for the game (currently always 2).
- `per_turn_deadline_ms` is the wall-clock budget per `observation_request`. Default 30000.
  Must be a positive integer; servers may impose an upper bound (default 600000).
- `per_action_retry_budget` is the number of `action_rejected` cycles allowed per turn before
  the match aborts with `adapter_error`. Default 3. Range: 0..10.
- `disconnect_grace_ms` is how long the server keeps the match alive after a peer's WS closes.
  Default 30000.

Success response (`HTTP 201 Created`):

```json
{
  "match_id": "abc123...",
  "game_id": "connect4",
  "game_schema_version": 1,
  "schema_version": 3,
  "lifecycle": "created",
  "per_turn_deadline_ms": 30000,
  "per_action_retry_budget": 3,
  "disconnect_grace_ms": 30000,
  "seat_0_url": "ws://host/matches/abc123.../play?seat=0",
  "seat_1_url": "ws://host/matches/abc123.../play?seat=1"
}
```

Error responses:

- `HTTP 400` `{"error": {"code": "unknown_game", "message": "..."}}` — unknown `game_id`.
- `HTTP 400` `{"error": {"code": "invalid_config", "message": "...", "details": {...}}}` — config
  validation failed; `details` carries the originating `DomainErrorPayload`.
- `HTTP 400` `{"error": {"code": "invalid_request", "message": "..."}}` — malformed body.
- `HTTP 400` `{"error": {"code": "schema_version_unsupported", "message": "..."}}` — the client's
  `supported_schema_versions` does not include the server's wire version (v3).
- `HTTP 413` `{"error": {"code": "request_too_large", "message": "..."}}` — body over 64 KiB.
- `HTTP 429` `{"error": {"code": "rate_limited", "message": "..."}}` — match-creation cap hit.
- `HTTP 503` `{"error": {"code": "server_busy", "message": "..."}}` — the server is at its
  match capacity and every tracked match is running (§13).
- `HTTP 500` `{"error": {"code": "server_error", "message": "..."}}` — internal failure.

#### `GET /matches/{match_id}`

Success (`HTTP 200`):

```json
{
  "match_id": "...",
  "game_id": "connect4",
  "lifecycle": "running",
  "schema_version": 3,
  "current_seat": 0,
  "turn_count": 4,
  "players": [
    {"player_id": "p0", "label": "alice", "seat": 0},
    {"player_id": "p1", "label": "bob", "seat": 1}
  ],
  "result": null,
  "abort": null
}
```

Errors:

- `HTTP 404` `{"error": {"code": "match_not_found", "message": "..."}}`.

#### `GET /matches/{match_id}/public-transcript` (Phase 40)

Success (`HTTP 200`): the `RuntimeTranscriptPayload` (§17) of an ended match, **exactly the
transcript a spectator received** in `match_finished` or `match_aborted`. For a
hidden-information game that is the public view (`view: "public"`): no hand, no private event,
and the chance outcomes as the public saw them. A perfect-information game has nothing to hide,
so its transcript is the full one (`view: "full"`). Finished and aborted matches are both
served. The response carries `Cache-Control: private, no-store`: the URL is a capability.

The server keeps these transcripts in a store that outlives the WebSocket connections and the
registry's own retention. With a durable store configured (see `docs/DEPLOYMENT.md`), it also
outlives a restart. Only the public transcript is ever stored or served: holding the `match_id`
is not holding a seat, and seat-scoped transcripts are not available over HTTP.

Retention is a server setting: by default a transcript is kept for 7 days from the end of the
match, and at most 10,000 transcripts (plus a byte cap) are kept, oldest dropped first. A
single transcript over the per-record cap (64 MiB with a durable store, 4 MiB in memory) is not
stored. The caps are global, so many long matches from one client can push out older
transcripts sooner than their TTL; size the byte cap for the deployment (docs/DEPLOYMENT.md).

Errors:

- `HTTP 404` `{"error": {"code": "match_not_found", ...}}`: unknown or malformed id, expired,
  or never stored (the store refused or failed; the match itself ended normally).
- `HTTP 409` `{"error": {"code": "transcript_not_ready", ...}}`: the match is still running, or
  has just ended and its transcript is being stored. It is available by the time
  `match_finished` / `match_aborted` has been sent; retry.
- `HTTP 429` `{"error": {"code": "rate_limited", ...}}`: per-IP read cap (§13).

#### `GET /games`

Success (`HTTP 200`):

```json
{
  "games": [
    {
      "game_id": "connect4",
      "game_schema_version": 1,
      "config_schema": { /* JSON Schema emitted by the game serializer */ },
      "min_seats": 2,
      "max_seats": 2
    },
    {
      "game_id": "tictactoe",
      "game_schema_version": 1,
      "config_schema": { ... },
      "min_seats": 2,
      "max_seats": 2
    }
  ]
}
```

The `config_schema` field is a JSON Schema document derived from the game's existing Pydantic
config model via `Serializer.config_schema()`. Clients use it to validate user-supplied configs
before calling `POST /matches`.

## 5. Lifecycle

A match progresses through a finite set of states, server-authoritative:

```
created  ─── both seats joined ───►  running  ─── result reached ───►  finished
   │                                    │
   │                                    └── timeout / disconnect / abort ──►  aborted
   └── creator gives up before joiner arrives ──────────────────────────────►  aborted
```

States match `arena.runtime.SessionLifecycle` (`created`, `running`, `finished`, `aborted`). The
server never invents new lifecycle states; this preserves transcript replay determinism.

## 6. Envelope

Every WebSocket message is a single JSON object with this shape:

```json
{
  "type": "<message_type>",
  "schema_version": 1,
  "match_id": "<match_id>",
  "seat": 0,
  "turn_id": "<client-generated UUID, optional>",
  "payload": { ... }
}
```

Field rules:

| Field | Required | Notes |
|-------|----------|-------|
| `type` | Always | One of the message types in §8. |
| `schema_version` | Always | Currently `3` (§7.1). Servers and Clients reject unknown major versions. |
| `match_id` | Always | Echoed back on every message after the handshake completes. |
| `seat` | Sometimes | Required on Client→Server messages once joined; optional on broadcasts. |
| `turn_id` | Required on `action_response` | Client-generated UUID4; idempotency key. |
| `payload` | Always | Message-specific JSON. May be empty `{}`. |

Unknown envelope fields are ignored by both sides (forward compatibility). Unknown payload fields
inside known message types are also ignored.

## 7. Schema versioning policy

- The integer `schema_version` covers the **envelope and message payload shapes**, not game configs.
- Bumped **only** for: removed fields, renamed fields, type changes, semantic changes to existing
  fields, new required fields.
- **Not** bumped for: new optional fields with safe defaults, new message types that older clients
  can ignore, additive enum values.
- "Unknown fields ignored" applies only to **optional** unknowns. A future version that promotes a
  field from optional to required must bump `schema_version`. SDKs must not silently ignore a field
  whose absence would change protocol semantics; the version bump is the signal.
### 7.1 Version history

| Version | Shipped in | What changed |
|---------|-----------|--------------|
| 1 | v1 (Phases 0-35) | Initial protocol. |
| 3 | Phase 38 | **Per-recipient payloads**, so hidden-information games can be served. `turn_committed` carries the recipient's own `post_snapshot`, a new `public_snapshot`, and only the events and chance-outcome parts the recipient may see. Events record `is_public`/`audience` when private. Transcripts (runtime and match) declare `view` (`"full"`, `"seat"`, `"public"`) and `viewer_seat`. Seats get `"seat"` transcripts and spectators `"public"` ones, and only a `"full"` transcript can be replayed. `welcome.match_config` is the seat's view, and `welcome.transcript` replays the seat's history on reconnect (§11). `POST /matches` accepts `supported_schema_versions`. New abort reason `turn_limit_exceeded`: the server caps every match's length. For a perfect-information game every view is the full one, so payloads differ from v2 only by the added fields. |
| 2 | Phase 37 | Transcript turns gained a `kind`. A **chance turn** has no seat and no action — nobody chose it — so `turns[].seat` and `turns[].action` became nullable in `match_finished.transcript` and `match_aborted.transcript`. `turn_committed.events` became load-bearing: it used to be an empty list, harmless while every game was deterministic because a client could recompute anything it missed, but a chance outcome cannot be recomputed. A chance turn carries the recorded `outcome` (game-specific JSON; null on action turns). Replay applies it and never re-rolls, so a transcript validates without the seed. **The seed is never sent**: the server's match object holds it, and it appears in no config, state, snapshot, event, or transcript. |

**Decode and emit are separate.** A server emits its own `schema_version` but accepts every version
it can still read — see `SUPPORTED_WIRE_SCHEMA_VERSIONS`. A build that can only read what it writes
cannot migrate without a flag day.

**Negotiation is strict: a server serves only its own version.** It accepts a connection
(`hello`, a reconnect `hello`, or `spectator_hello`) **iff its emitted version is in
`supported_schema_versions`**, and otherwise closes with `4400` (`schema_version_mismatch`). A
client that cannot read the current version is refused rather than served an older shape. For a
hidden-information game an older shape could not even be produced without leaking, since v1 and v2
have no per-recipient payloads. A client should advertise every version it reads; the reference
SDK sends `[1, 2, 3]`. `POST /matches` accepts the same list (optional), so a creator learns of a
mismatch before handing out seat URLs.
- This policy is **independent** of game-config schema evolution. Each registered game carries its
  own `game_schema_version` (integer) returned by `GET /games` and echoed in `welcome.match_config`.
  Adding an optional Connect 4 config field is a Connect 4 schema bump, not an envelope schema
  bump. v1 servers reject `POST /matches` with an unknown `game_schema_version` via
  `HTTP 400 invalid_config`. SDKs must validate user-supplied configs against the
  `game_schema_version` declared in `GET /games` before sending `POST /matches`.

## 8. Message types

Every message uses the envelope above. The tables below define `payload` shapes only.

### 8.1 `hello` (Client → Server, first frame after WS open)

```json
{
  "client_name": "arena-sdk-python",
  "client_version": "0.1.0",
  "supported_schema_versions": [1],
  "auth": null,
  "requested_seat": 0,
  "resume_token": null
}
```

- `auth`: reserved field, currently always `null`. Servers must accept `null`; non-null values are
  ignored in v1 but reserved for future token-based auth.
- `requested_seat`: integer; server validates against the URL's seat query param. Mismatch closes
  with code `4422` (`malformed_envelope`).
- `resume_token`: string returned by the server in `welcome.resume_token`, used to resume a
  dropped connection (§11). `null` means "fresh join".

If the seat is already occupied by a live connection, the server closes with code `4409`
(`seat_taken`).

### 8.2 `welcome` (Server → Client, response to `hello`)

```json
{
  "match_id": "...",
  "game_id": "connect4",
  "game_schema_version": 1,
  "seat": 0,
  "lifecycle": "created",
  "schema_version": 1,
  "negotiated_schema_version": 1,
  "resume_token": "<opaque>",
  "per_turn_deadline_ms": 30000,
  "per_action_retry_budget": 3,
  "disconnect_grace_ms": 30000,
  "players": [
    {"player_id": "p0", "label": "alice", "seat": 0},
    {"player_id": "p1", "label": "bob", "seat": 1}
  ],
  "match_config": { /* this seat's view of the validated game config */ },
  "transcript": null
}
```

- `negotiated_schema_version` is the integer chosen by the server from §7's negotiation rule. v1
  servers always set this to `1`.
- `resume_token` is opaque to the Client. **It is bound server-side to the (match_id, seat) pair**
  and is rotated on every successful resume. A token presented for a different seat or match is
  rejected and the connection closes with `4401` (`unauthorized`).
- `match_config` is the validated game config that was sent to `POST /matches`, normalized by the
  game's serializer, **as this seat may see it** (v3). Games keep secrets out of config (a seed
  there would be public), so in practice this is the whole config.
- `transcript` (v3) is null on a first connect. On a **reconnect** it is this seat's runtime
  transcript so far (`view: "seat"`), the replay §11 promises. It holds exactly the turns the seat
  was sent live, so reconnecting recovers what was missed and adds no information.
- `per_turn_deadline_ms`, `per_action_retry_budget`, and `disconnect_grace_ms` echo the values
  locked at match creation; SDKs use them to size internal state.

### 8.3 `match_state` (Server → Client, broadcast on lifecycle change)

```json
{
  "lifecycle": "running",
  "current_seat": 0,
  "turn_count": 0,
  "result": null,
  "abort": null
}
```

Sent when:
- both seats have joined (`created` → `running`)
- a turn has been committed
- the match reaches a terminal result (`running` → `finished`)
- the match is aborted (`running`/`created` → `aborted`)

### 8.4 `observation_request` (Server → Client, only to the active seat)

```json
{
  "observation_request": <ObservationRequestPayload>,
  "deadline_ms": 30000
}
```

Where `<ObservationRequestPayload>` is exactly the payload defined by
`arena.adapters.in_process.ObservationRequestPayload`. The `deadline_ms` is the wall-clock budget
the server will wait for the action; on expiry the server aborts the match with reason
`turn_deadline_expired`.

### 8.5 `action_response` (Client → Server)

```json
{
  "action_response": <ActionResponsePayload>
}
```

The envelope's `turn_id` is required and must be a fresh UUID4 per turn. If the server has already
committed a turn for this `turn_id`, it ignores the message (idempotent). If the action is
illegal, the server replies with `action_rejected` (§8.6) and waits for another `action_response`
from the same seat against the same observation.

### 8.6 `action_rejected` (Server → Client)

```json
{
  "turn_id": "...",
  "error": <DomainErrorPayload>,
  "retries_remaining": 2
}
```

Where `<DomainErrorPayload>` is exactly `arena.adapters.in_process.DomainErrorPayload`. The
initial value of `retries_remaining` equals `welcome.per_action_retry_budget` (default 3). The
server decrements the counter exactly **once per unique `turn_id`** that was rejected; duplicate
`action_response` frames carrying an already-rejected `turn_id` are silently dropped (§12) and do
**not** decrement.

**Termination ordering on retry-budget exhaustion** (sent in this exact order over the same
connection, no interleaving):

1. `action_rejected` carrying `retries_remaining: 0` and the final `<DomainErrorPayload>`.
2. `match_state` with `lifecycle="aborted"` and abort reason `adapter_error`.
3. `match_aborted` carrying the full abort metadata and the final transcript (§8.9).
4. WebSocket close frame with code `1000`.

The server stops reading once it has sent step 1, so `action_response` frames arriving after
it go unanswered (see §8.10's action-after-terminal rule).

### 8.7 `turn_committed` (Server → Client, broadcast)

```json
{
  "turn_record": <TurnRecordPayload>,
  "post_snapshot": <SnapshotPayload>,
  "events": [ <runtime/game events> ]
}
```

Sent once per committed turn. Both seats and every spectator receive it, **each in its own
view** (v3):

- `post_snapshot` is the recipient's view: its seat's for a seat, the public view for a spectator.
- `public_snapshot` (v3) is the public view, the same for every recipient. For a
  perfect-information game it equals `post_snapshot`.
- `events` holds only the events the recipient may see. A domain event may be private to some
  seats (for example "you were dealt these dice"). Its serialized form then carries
  `"is_public": false` and `"audience": [seats]`. A public event carries neither key.
- `turn_record.outcome` of a chance turn is the recipient's view of the outcome. A spectator may
  get `{}` for a private deal.
- `turn_index` is **0-based** here and in transcripts. (`TurnAccepted` runtime events count
  1-based.)

Since v2 one step can commit several turns. An accepted action is followed by one `turn_committed`
for each chance node it leads to (for example the die roll after a Pig `roll`). A game that opens at
a chance node sends those turns before the first `match_state`. Each carries its own `turn_index`.

### 8.8 `match_finished` (Server → Client, broadcast)

```json
{
  "result": <ResultPayload>,
  "transcript": <RuntimeTranscriptPayload>
}
```

Terminal message before the server closes the connection with code `1000` (normal closure).

### 8.9 `match_aborted` (Server → Client, broadcast)

```json
{
  "abort": <AbortMetadataPayload>,
  "transcript": <RuntimeTranscriptPayload>
}
```

Terminal message before close. The connection closes with code `1000`; the abort metadata carries
the failure reason.

### 8.10 `ping` / `pong` (bidirectional)

```json
{ "nonce": "<echoed>" }
```

Sent every 20 seconds by the server to the **active seat** while its turn is open. An off-turn
seat is not pinged: the server does not read from it, and it is checked when its turn comes
(the protocol-level keepalive of §3 covers every connection meanwhile). Clients must reply with
`pong` echoing the same `nonce` within 20 seconds. Two consecutive missed `pong` responses close
the connection with code `4408` (`heartbeat_timeout`).

Heartbeat-driven close is one of several ways a peer may disappear (others: explicit close, TCP
RST, network partition). The disconnect grace period (§11) starts at the moment of close,
regardless of which mechanism triggered it.

**Action-after-terminal rule** (referenced from §8.6): once the server has emitted `match_state`
with a non-`running` lifecycle, it reads nothing more from either seat: it sends the terminal
frame (`match_finished` or `match_aborted`) and closes both play channels. Any `action_response`
still in flight is never read, and no reply is sent. The error code `match_already_finished` is
reserved and not currently emitted.

The match's lifecycle transition itself is **atomic at the server**: a single state mutation
flips `running → finished` or `running → aborted`. Frames arriving "during" that transition
either land on `running` (and are processed normally) or land on the post-transition state (and
follow this rule). There is no third outcome.

### 8.11 `error` (Server → Client, non-terminal)

```json
{ "code": "<error_code>", "message": "..." }
```

For protocol-level issues that don't terminate the match (e.g., malformed message). The Client
should log and continue.

### 8.13 spectator_hello / spectator_welcome (Phase 36)

Added for the spectator channel. New message types rather than widening `hello`/`welcome`,
because §7 bumps the schema for type or semantic changes to existing fields but explicitly allows
new message types that older clients can ignore. `WelcomeBody.seat` is `int` under `strict=True`
and cannot carry `null`, so reusing `welcome` for a seatless client was not possible without a bump.

`spectator_hello` (Client → Server), sent as the first frame on the spectate channel:

```json
{
  "type": "spectator_hello",
  "schema_version": 1,
  "payload": {
    "client_name": "my-viewer",
    "client_version": "0.1.0",
    "supported_schema_versions": [1]
  }
}
```

No `requested_seat` and no `resume_token`: possession of the `match_id` is the capability, and a
reconnecting spectator simply says hello again.

`spectator_welcome` (Server → Client) answers it and carries the attach-time history:

```json
{
  "type": "spectator_welcome",
  "schema_version": 1,
  "match_id": "...",
  "payload": {
    "match_id": "...",
    "game_id": "connect4",
    "game_schema_version": 1,
    "lifecycle": "running",
    "schema_version": 1,
    "negotiated_schema_version": 1,
    "players": [{"player_id": "p0", "label": "alice", "seat": 0}],
    "turn_count": 4,
    "transcript": { }
  }
}
```

`transcript` is the public transcript, which for a perfect-information game is the full one, and is
`null` before the match starts. Bundling it into the welcome means a spectator joining mid-match can
render immediately; there is no separate history message for a running match. It is queued before
the connection joins the broadcast set, so live frames always follow the history they continue.

If the match is already `finished` or `aborted`, the server sends `spectator_welcome` and closes.

## 9. Error taxonomy

WebSocket close codes (4000-4999 are application-defined):

| Code | Name | Meaning |
|------|------|---------|
| `1000` | `normal_closure` | Match completed or aborted; transcript already delivered. |
| `1003` | `unsupported_data` | Binary frame received. |
| `4400` | `schema_version_mismatch` | No mutually supported `schema_version`. |
| `4401` | `unauthorized` | A `resume_token` bound to the other seat (§11). Further uses reserved for v2 auth. |
| `4404` | `unsupported_endpoint` | No such WebSocket endpoint. |
| `4408` | `heartbeat_timeout` | Two consecutive missed `pong`s. |
| `4409` | `seat_taken` | Seat already has a live connection. |
| `4410` | `match_not_found` | `match_id` does not exist (or expired with server restart). |
| `4422` | `malformed_envelope` | Envelope failed validation, or no `hello` / `spectator_hello` within 10 s of connecting (reason `hello_timeout`). |
| `4429` | `rate_limited` | Connection or match-creation rate cap hit (v1 has hardcoded caps). |
| `4500` | `server_error` | Internal server failure. If the match driver fails, the match aborts with reason `runtime_error`, both seats receive `match_aborted`, and both close `4500`. |

In-band error codes carried in `error.code` and `action_rejected.error.code`:

| Code | Source | Meaning |
|------|--------|---------|
| `illegal_action` | rules engine | Action rejected by `apply_action`. |
| `wrong_seat` | server | Action sent by a non-active seat. |
| `wrong_turn` | server | Action did not match the current observation. |
| `match_already_finished` | server | Reserved; not currently emitted (see §8.10). |
| `turn_deadline_expired` | server | `deadline_ms` elapsed; match aborts. |
| `adapter_error` | server | Retry budget exhausted on `action_rejected`. |
| `protocol_violation` | server | Message arrived in an invalid lifecycle state. |

Domain-level errors raised inside `arena.core` retain their original `code`, `message`, and
`details` fields; the wire never repackages them.

## 10. Match creation and join flow

1. Creator sends `POST /matches` with `{game_id, game_config, players: [{label}, {label}],
   per_turn_deadline_ms}`.
2. Server returns `{match_id, seat_0_url, seat_1_url}`. Both URLs are
   `WS /matches/{match_id}/play?seat=N`. Lifecycle starts at `created`.
3. Creator opens `seat_0_url`; sends `hello`; receives `welcome` with `lifecycle="created"`.
4. Creator forwards `seat_1_url` to the joiner out-of-band (Discord, email, etc.).
5. Joiner opens `seat_1_url`; sends `hello`; receives `welcome` with `lifecycle="created"`.
6. As soon as the second `hello` is accepted, the server emits `match_state` with
   `lifecycle="running"` to both seats and immediately follows with an
   `observation_request` to seat 0.
7. The match proceeds turn by turn until `match_finished` or `match_aborted`.

The creator becomes seat 0 by convention; the joiner becomes seat 1. There is no client-side seat
negotiation in v1.

## 11. Disconnects and reconnection

- **Disconnect during own turn**: server starts the disconnect grace period (default 30s,
  configurable at match creation via `disconnect_grace_ms`). If the seat reconnects with a valid
  `resume_token` within the window, the in-flight `observation_request` is re-sent (with the
  remaining `deadline_ms` recomputed from the original wall-clock deadline) and play continues.
  If the deadline expires inside the grace window, the match aborts with reason
  `turn_deadline_expired`. Otherwise the match aborts with reason `peer_disconnected`.
- **Disconnect off-turn**: server keeps the match alive. When the dropped seat's turn arrives, the
  same grace period applies before issuing the `observation_request`.
- **Both seats disconnected**: there is no separate rule. The active seat's grace period (or
  the turn deadline, whichever ends first) decides the match; the off-turn seat's absence is
  noticed when its turn comes.
- **Heartbeat timeouts** (§8.10) are disconnects too: the `4408` close starts the grace period,
  and if the seat does not resume the match aborts with reason `heartbeat_timeout`.
- **Running matches are reachable only by resume token.** Once both seats have joined, a
  `hello` without a `resume_token` closes with `4409 seat_taken`, even while a seat's grace
  period runs. (Before this rule, a seat whose socket had dropped could be claimed by anyone
  holding the `match_id`, who then resumed with the fresh token and read that seat's view.)
- **Server restart**: matches do not survive. Reconnects with a stale `resume_token` close with
  `4410` (`match_not_found`).
- **Resume protocol**: reconnecting client sends `hello` with `resume_token`. Server validates the
  token's `(match_id, seat)` binding; mismatch closes with `4401` (`unauthorized`). On success the
  server responds with `welcome` containing the latest lifecycle, a freshly-rotated
  `resume_token`, and (v3) **`welcome.transcript`: the seat's own transcript so far**. The replay
  rides inside the welcome rather than as separate frames. The client reaches **logically
  equivalent state** to one that never disconnected. Framing is not byte-identical; the resulting
  state is. The server then sends `match_state` and, if the reconnecting seat is the active seat,
  re-sends the in-flight `observation_request`, so the client always knows what to act on.
- **A resume is only for a running match.** Before both seats have joined there is nothing to
  resume: a `hello` with a `resume_token` closes with `4409 match_not_started`, and the client
  should send a fresh `hello`.
- **The reconnected connection takes over immediately**, active seat or not. The old socket, if
  still open (half-open TCP), is closed with `1000 superseded`. The server builds the
  replay transcript and swaps the connection into the broadcast set in one uninterrupted step, so
  every turn is either in `welcome.transcript` or delivered live afterwards, never both and never
  neither.
- **No seat can be claimed or resumed once a match has ended** (finished, aborted, or its driver
  crashed): a `hello` closes with `4410 match_over`, and resume tokens are invalidated. A finished
  match stays in the registry for late reads and releases its seats. Without this rule, anyone
  holding the `match_id`, including every spectator, could claim a seat and read that seat's
  private transcript.
- **Capability caveat.** Seat URLs and the spectate URL share one `match_id`, so until both seats
  are claimed, anyone who can spectate can take a seat. Share a hidden-information match's id only
  with its players until both have joined. Separate spectate capabilities belong with real
  authentication, which is deferred.

**Information model (v3).** A reconnecting seat is replayed its *own* view: the same per-seat
redaction as the live frames, so it learns nothing it would not have learned by staying
connected. This is what makes resuming safe for hidden-information games. v1 and v2 relied on
every game being perfect-information, and refused to serve any game that declared hidden
information.

## 12. Idempotency

- `action_response` carries a Client-generated `turn_id` (UUID4). Servers maintain a per-match
  set of **observed** `turn_id`s, partitioned into "committed" and "rejected". Both states are
  terminal for that `turn_id`.
- WebSocket guarantees per-connection FIFO delivery; servers process `action_response` frames
  strictly in arrival order on a given connection. There is no inter-connection ordering question
  in v1 because only one connection per seat may be live at a time (§4, §11).
- A duplicate `action_response` (same `turn_id` as a committed or rejected one) is silently
  dropped by the server. It does **not** decrement the retry counter (§8.6), does **not** advance
  the match, and does **not** generate any reply frame.
- A `turn_id` reused **across turns** by the same seat (i.e., a `turn_id` already committed in
  turn N being submitted again as the action for turn N+1) is treated the same way: dropped
  silently. Clients must mint a fresh UUID4 per turn.
- The committed/rejected set is in-memory and does not survive a server restart; once the
  `match_id` is no longer in `MatchRegistry`, reconnects close with `4410` (`match_not_found`).
- Server-broadcast messages (`turn_committed`, `match_state`) carry the integer `turn_count`;
  clients deduplicate by it.

## 13. Rate limits (v1, hardcoded)

> **Implementation status (Phase 40 Slice 0): every cap below is enforced.**
>
> | Cap | Status |
> |-----|--------|
> | Max concurrent WebSocket connections per source IP | ✅ closes `4429` |
> | Max WebSocket opens per source IP per minute | ✅ closes `4429` |
> | Max match creations per source IP per minute | ✅ returns `HTTP 429 rate_limited` |
> | Max concurrent seat connections per match | ✅ closes `4429` |
> | Max concurrent spectators per match | ✅ closes `4429` |
> | Max `action_response` per match per second | ✅ throttles (see below) |
> | Max public-transcript reads per source IP per minute | ✅ returns `HTTP 429 rate_limited` |
>
> **Scope of the action cap.** It counts action frames the server actually *reads*, which are the
> ones from the seat whose turn it is. An off-turn seat's frames sit unread in its socket buffer
> until its turn arrives, so they are not counted when sent. The cap therefore bounds work the
> match loop performs, not raw inbound traffic — the per-IP and per-match connection caps are what
> bound the latter. Exceeding it throttles (see below); it never closes a connection.
>
> Implementation lives in `arena/server/rate_limits.py`. Caps are injectable: the test suite runs
> with `RateLimiter.unlimited()` because the whole suite shares one client address.
>
> **The action cap throttles instead of closing (Phase 38 hardening).** It used to close the seat
> with `4429` at 2 actions per second. Two scripted or fast bots exceed that within one move each,
> and every real-server demo then aborted as `peer_disconnected`, blaming a seat that did nothing
> wrong. CI never saw it because tests run unlimited. The server now delays reading the next action
> until the window has room, which bounds the loop's work just as closing did. The delay is the
> server's, not the seat's: an action that has arrived counts as on time, and the wait is not charged
> against the per-turn deadline (the window is shared by both seats). The cap is 10 per second.

- Max concurrent WebSocket connections per source IP: **8**. "Source IP" is the TCP peer, or the
  right-most entry of the operator's trusted client-address header (§ DEPLOYMENT); an IPv6
  address counts by its /64, and an IPv4-mapped one as its IPv4 address.
- Max WebSocket opens per source IP per minute, seats and spectators alike: **60**. The
  concurrent cap alone let one client attach and detach a spectator in a loop, and each attach
  to a long match costs the server a welcome of up to megabytes.
- Max match creations per source IP per minute: **5**. Every attempt counts, and the cap is
  checked before the request body is read. A create body is at most 64 KiB (`413
  request_too_large`); `players` has at most two entries, and a label at most 64 characters.
- Max `action_response` messages per match per second: **10**, enforced by throttling (see above).
- Max concurrent seat connections per match: **4**. A connection claims its per-match slot only
  once its fresh `hello` is valid; a resume with a valid token claims none and is never refused
  for this cap: sockets that never said hello used to hold the slots and lock a
  dropped seat out of its own reconnect. Every new connection has 10 s to send its hello.
- Max concurrent spectators per match: **16**, counted separately, so spectators can never
  lock a seat out of its own reconnect.
- Max public-transcript reads per source IP per minute (Phase 40): **30**.

The server also bounds its match registry: at most 1000 matches. When it is full it sheds
finished matches first, then never-started ones (which also expire after an hour), oldest
first, and never a running match. Every age counts from the match's last change: a finished
match is kept an hour after it *ended* (however long it ran), and a running match is given up
only after 24 hours without a committed turn. If nothing can be shed, `POST /matches` returns `503
server_busy`. Never-started matches the server sheds close any waiting seat or spectator with
`4410 match_expired`.

Exceeding a connection or creation cap closes the connection with `4429` (HTTP `429` for match
creation); the action cap throttles. The same caps apply to malformed
or `protocol_violation`-emitting connections; a peer flooding the server with malformed frames
hits the per-IP connection cap and is shed. This bounds the cost of the "logging DoS" attack
surface to the cost of opening 8 sockets.

## 14. Logging contract

The server emits one structured JSON log line per significant event. Every line contains:

```json
{
  "timestamp": "...",
  "level": "info|warning|error",
  "event": "<event_name>",
  "match_id": "...",
  "seat": 0,
  "schema_version": 1,
  ...event-specific fields
}
```

Documented `event` values: `match_created`, `match_started`, `seat_connected`, `seat_disconnected`,
`turn_committed`, `action_rejected`, `turn_deadline_expired`, `match_finished`, `match_aborted`,
`heartbeat_timeout`, `protocol_violation`.

Match transcripts are **not** logged (PII-by-default principle, even though current games are
PII-free). They live in the dedicated transcript output channel.

## 15. Test contract (informative)

A conformant server passes:
- a happy-path Connect 4 match with two scripted Clients
- a happy-path Tic-Tac-Toe match with two scripted Clients
- illegal action → `action_rejected` → retry → success
- retry budget exhausted → `match_aborted` with `adapter_error`
- per-turn deadline expired → `match_aborted` with `turn_deadline_expired`
- mid-turn disconnect within grace → resume succeeds, transcript validates
- mid-turn disconnect past grace → `match_aborted` with `peer_disconnected`
- duplicate `action_response` (same `turn_id`) → idempotent, no double-commit
- malformed envelope → `error` event, connection survives
- binary frame → close `1003`
- heartbeat miss → close `4408`

A conformant SDK passes the mirror suite from the Client side.

## 16. Forward compatibility notes

- The `auth` field is reserved on `hello` so adding token-based auth in v2 does not bump
  `schema_version`.
- The `spectate` URL is reserved so adding read-only spectators in v2 does not break clients.
- The `resume_token` is opaque so server-side reconnection strategies can evolve without changing
  the wire shape.
- Game-config evolution is independent: a new optional Connect 4 field is a Connect 4 schema
  change, not a wire change. v2 may extend `match_config` with hidden-information scoping, gated
  by a `game_schema_version` bump per-game.

## 17. Payload reference

The bodies of `observation_request`, `action_response`, `action_rejected`, `turn_committed`,
`match_finished`, and `match_aborted` are not invented by the wire protocol — they reuse the
existing `arena.adapters.in_process` and `arena.runtime` payload models verbatim, which are the
canonical Pydantic v2 definitions plus their JSON Schema output.

To keep this document a viable language-agnostic source of truth, every non-Python SDK MUST
generate its own type bindings from the **JSON Schemas published alongside the server** at:

- `GET /games` → per-game `config_schema` (Pydantic-derived JSON Schema)
- `GET /schemas/payloads` → JSON Schema document covering: `ObservationRequestPayload`,
  `ActionResponsePayload`, `DomainErrorPayload`, `TurnRecordPayload`, `SnapshotPayload`,
  `ResultPayload`, `AbortMetadataPayload`, `RuntimeTranscriptPayload`, `SessionStatusPayload`,
  `RuntimeEventPayload`, `PlayerRecordPayload`, plus every envelope message body in §8.

Servers MUST expose `GET /schemas/payloads` at the same `schema_version` declared by the
envelope. The endpoint returns:

```json
{
  "schema_version": 1,
  "schemas": {
    "ObservationRequestPayload": { /* JSON Schema */ },
    "ActionResponsePayload":    { /* JSON Schema */ },
    "DomainErrorPayload":       { /* JSON Schema */ },
    "TurnRecordPayload":        { /* JSON Schema */ },
    "SnapshotPayload":          { /* JSON Schema */ },
    "ResultPayload":            { /* JSON Schema */ },
    "AbortMetadataPayload":     { /* JSON Schema */ },
    "RuntimeTranscriptPayload": { /* JSON Schema */ },
    "SessionStatusPayload":     { /* JSON Schema */ },
    "RuntimeEventPayload":      { /* JSON Schema */ },
    "PlayerRecordPayload":      { /* JSON Schema */ },
    "Envelope":                 { /* JSON Schema, discriminated union of message types */ }
  }
}
```

The Python reference SDK (`arena.sdk`) consumes these schemas at install time via the bundled
Pydantic models; it does not need to fetch from `/schemas/payloads` at runtime. Non-Python SDKs
fetch once during build/codegen and pin to the same `schema_version` they support. Servers MUST
keep `/schemas/payloads` byte-stable for a given `schema_version`; any change is a version bump.

**Envelope consistency (v3).** The JSON Schemas describe each field; a `RuntimeTranscriptPayload`
or `SessionStatusPayload` must also agree with itself, and the reference implementation rejects
one that does not:

- `lifecycle` is one of `created`, `running`, `finished`, `aborted`, and `abort` is present
  exactly when it is `aborted`;
- players have distinct seats and distinct `player_id`s;
- `viewer_seat` is a seat exactly when `view` is `"seat"`, and `null` otherwise;
- a transcript's `view` and `viewer_seat` equal those of the `match_transcript` it wraps (a
  pre-v3 inner transcript carries none and is full);
- in a view other than `"full"`, `abort.cause_message` is `null` (the text of an exception can
  carry anything, including an agent's reasoning about its own hand).

**Key payload shapes** (informative summary; the JSON Schemas are authoritative):

- `ObservationRequestPayload`: `{schema_version, match_id, game_id, seat, observation,
  legal_actions}`. `observation` and `legal_actions` are game-specific JSON-safe data produced by
  the game's `Serializer`.
- `ActionResponsePayload`: `{schema_version, match_id, game_id, seat, action}`. `action` is
  game-specific JSON-safe data accepted by the game's `Serializer.load_action(...)`.
- `DomainErrorPayload`: `{code, message, details}`. `code` is the simulation-layer exception's
  canonical name (e.g. `"illegal_action"`, `"wrong_player"`, `"game_finished"`,
  `"invalid_config"`); `details` carries arbitrary JSON-safe metadata.
- `TurnRecordPayload`: `{turn_index, kind, seat, action, outcome, events, post_snapshot}`
  mirroring `arena.match.TurnRecord`. `kind` is `"action"` or `"chance"` (v2). An action turn has
  `seat` and `action` and a null `outcome`; a chance turn has null `seat` and `action` and a
  game-specific `outcome`. `post_snapshot` is a full game-specific snapshot envelope.
- `SnapshotPayload`: `{schema_version, game_id, state, terminal, result}` from
  `Serializer.dump_snapshot(...)`. Required to rehydrate.
- `ResultPayload`: `{kind: "win"|"draw", winner_seat, ...}` mirroring `arena.core.results`.
- `AbortMetadataPayload`: `{reason, message, cause_type, cause_message}` from
  `arena.runtime.AbortMetadata`. `reason` is one of the documented runtime abort codes
  (e.g. `peer_disconnected`, `turn_deadline_expired`, `adapter_error`, `user_quit`,
  `turn_limit_exceeded`).
- `RuntimeEventPayload`: `{event_scope: "runtime", event_type, ...event-specific fields}`.

## 18. Message broadcast matrix

Who receives each Server → Client message. Spectators are live as of Phase 36.

| Message type        | Active seat | Inactive seat | Spectators |
|---------------------|-------------|---------------|------------|
| `welcome`           | recipient only (response to that seat's `hello`) | recipient only | n/a — spectators get `spectator_welcome` |
| `spectator_welcome` | n/a         | n/a           | recipient only (response to `spectator_hello`) |
| `match_state`       | yes         | yes           | yes                      |
| `observation_request` | **yes (only)** | no         | **never** |
| `action_rejected`   | **yes (only)** | no          | no                       |
| `turn_committed`    | yes         | yes           | yes                      |
| `match_finished`    | yes         | yes           | yes                      |
| `match_aborted`     | yes         | yes           | yes                      |
| `ping` / `pong`     | per-connection (independent of seat activity) | per-connection | per-connection |
| `error`             | per-connection (only the offending peer) | per-connection | per-connection |

Notes:

- "Inactive seat" includes seats currently in their disconnect grace period that later reconnect:
  the missed broadcasts are reconstructed via transcript replay on resume (§11).
- Spectators receive everything a seat receives except `observation_request` and
  `action_rejected`, which are addressed to a seat and a spectator holds none. A spectator that
  sends anything other than `ping`/`pong` gets an `error` with code `protocol_violation` and is
  disconnected.
- A spectator that cannot keep up is dropped rather than allowed to slow the match: once its
  outbound queue overflows the server closes it with `1000 spectator_too_slow`. Seats are never
  shed this way.
- Attach-time history rides in `spectator_welcome.transcript` (the public transcript; identical to
  the full one for a perfect-information game). There is no separate history message for a running
  match.
- Adding spectators required **no schema bump**: `spectator_hello` and `spectator_welcome` are new
  message types, which §7 permits. v3 then made every broadcast **per recipient**: each seat gets
  its own view and spectators the public view (§8.7). A spectator is sent no `turn_committed` for
  a turn its `spectator_welcome` transcript already carried.
- The server caps every match's length (default 5000 turns). A game that can loop forever
  (two Pig seats that only ever roll) aborts with `turn_limit_exceeded` rather than pinning
  server memory.
- `match_state` is the **only** lifecycle-transition signal; SDKs should drive their internal
  state machine off it rather than off `welcome.lifecycle` after the initial handshake.
