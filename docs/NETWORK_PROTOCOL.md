# AgentsArena Network Protocol (v1)

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
- Spectator streams (URL shape reserved; behavior deferred to v2)
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
  (unsupported data).
- One JSON message per WebSocket frame. No newline framing inside a frame.

## 4. URL shape

- `POST /matches` — create a match (HTTP).
- `GET /matches/{match_id}` — match status (HTTP, JSON, no auth).
- `GET /games` — list of supported game ids and their config schemas (HTTP, JSON).
- `WS /matches/{match_id}/play?seat={0|1}` — primary play channel (WebSocket).
- `WS /matches/{match_id}/spectate` — reserved for v2; servers must respond with close code
  `4404` (`unsupported_endpoint`) until implemented.

The unguessable `match_id` (>=128 bits of entropy via `secrets.token_urlsafe(16)`) is the
capability. Possession of the URL grants the right to join the match.

> **Known v1 information leak:** `GET /matches/{match_id}` exposes the opponent's `label` and the
> chosen `match_config` to any holder of the `match_id`. For the v1 trust model (you and a friend
> share the id out-of-band) this is by design. v2 will redact per-viewer.

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
  "disconnect_grace_ms": 30000
}
```

- `game_id` must appear in `GET /games`.
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
  "schema_version": 1,
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
- `HTTP 429` `{"error": {"code": "rate_limited", "message": "..."}}` — match-creation cap hit.
- `HTTP 500` `{"error": {"code": "server_error", "message": "..."}}` — internal failure.

#### `GET /matches/{match_id}`

Success (`HTTP 200`):

```json
{
  "match_id": "...",
  "game_id": "connect4",
  "lifecycle": "running",
  "schema_version": 1,
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
| `schema_version` | Always | Currently `1`. Servers and Clients reject unknown major versions. |
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
- **v1 servers always speak `schema_version=1`.** The `hello.supported_schema_versions` list and
  the negotiation flow exist to give v2+ servers a forward-compatible upgrade path without breaking
  v1 clients. Negotiation rule for any server: pick the highest integer present in both
  `hello.supported_schema_versions` and the server's own supported range; if no overlap, close with
  code `4400` (`schema_version_mismatch`) and a reason string naming the server's supported range.
  v1 servers reduce this to: accept the connection iff `1` is in `hello.supported_schema_versions`.
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
  "match_config": { /* the validated game config object */ }
}
```

- `negotiated_schema_version` is the integer chosen by the server from §7's negotiation rule. v1
  servers always set this to `1`.
- `resume_token` is opaque to the Client. **It is bound server-side to the (match_id, seat) pair**
  and is rotated on every successful resume. A token presented for a different seat or match is
  rejected and the connection closes with `4401` (`unauthorized`).
- `match_config` is the validated game config that was sent to `POST /matches`, normalized by the
  game's serializer.
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

`action_response` frames arriving after step 1 but before close are processed as in §8.10's
"action arrives after match is no longer running" rule: dropped silently if their `turn_id` is
already-known, otherwise replied with an `error` of code `match_already_finished`.

### 8.7 `turn_committed` (Server → Client, broadcast)

```json
{
  "turn_record": <TurnRecordPayload>,
  "post_snapshot": <SnapshotPayload>,
  "events": [ <runtime/game events> ]
}
```

Sent after every accepted action. Both seats receive it. Spectators (v2) will receive it too.

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

Sent every 20 seconds by the server, on every connected play channel regardless of whose turn it
is. Clients must reply with `pong` echoing the same `nonce` within 20 seconds. Two consecutive
missed `pong` responses close the connection with code `4408` (`heartbeat_timeout`).

Heartbeat-driven close is one of several ways a peer may disappear (others: explicit close, TCP
RST, network partition). The disconnect grace period (§11) starts at the moment of close,
regardless of which mechanism triggered it.

**Action-after-terminal rule** (referenced from §8.6): once the server has emitted `match_state`
with a non-`running` lifecycle, any subsequent `action_response` frame on the same connection is:

- silently dropped if its `turn_id` is in the per-match committed-or-rejected set (§12);
- otherwise replied with an `error` of code `match_already_finished`.

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

## 9. Error taxonomy

WebSocket close codes (4000-4999 are application-defined):

| Code | Name | Meaning |
|------|------|---------|
| `1000` | `normal_closure` | Match completed or aborted; transcript already delivered. |
| `1003` | `unsupported_data` | Binary frame received. |
| `4400` | `schema_version_mismatch` | No mutually supported `schema_version`. |
| `4401` | `unauthorized` | Reserved for v2 auth failures. |
| `4404` | `unsupported_endpoint` | Spectate / unknown endpoint requested. |
| `4408` | `heartbeat_timeout` | Two consecutive missed `pong`s. |
| `4409` | `seat_taken` | Seat already has a live connection. |
| `4410` | `match_not_found` | `match_id` does not exist (or expired with server restart). |
| `4422` | `malformed_envelope` | Envelope failed validation. |
| `4429` | `rate_limited` | Connection or match-creation rate cap hit (v1 has hardcoded caps). |
| `4500` | `server_error` | Internal server failure. |

In-band error codes carried in `error.code` and `action_rejected.error.code`:

| Code | Source | Meaning |
|------|--------|---------|
| `illegal_action` | rules engine | Action rejected by `apply_action`. |
| `wrong_seat` | server | Action sent by a non-active seat. |
| `wrong_turn` | server | Action did not match the current observation. |
| `match_already_finished` | server | Action sent after terminal lifecycle. |
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
- **Both seats disconnected**: match aborts after a longer grace period (default 60s).
- **Server restart**: matches do not survive. Reconnects with a stale `resume_token` close with
  `4410` (`match_not_found`).
- **Resume protocol**: reconnecting client sends `hello` with `resume_token`. Server validates the
  token's `(match_id, seat)` binding; mismatch closes with `4401` (`unauthorized`). On success the
  server responds with `welcome` containing the latest lifecycle and a freshly-rotated
  `resume_token`, then replays the runtime transcript via existing `dump_runtime_transcript(...)`
  so the client reaches **logically equivalent state** to a fresh joiner that received the full
  history (note: framing is not guaranteed byte-identical, only the resulting state is). If the
  reconnecting seat is the active seat, the in-flight `observation_request` is re-sent **after**
  the transcript replay so the client always knows what to act on. After replay, normal flow
  resumes.

**v1 information-model assumption.** The full-history replay is safe only because Connect 4 and
Tic-Tac-Toe are public-move perfect-information games: every move is broadcast to both seats the
moment it happens, so a reconnecting peer learns nothing it would not have learned by staying
connected. **Games with private state (hidden cards, fog of war, simultaneous moves) require a v2
extension** that scopes transcript replay per-seat. v1 servers must reject registration of any
game whose `GameDefinition` declares hidden information.

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

- Max concurrent WebSocket connections per source IP: **8**.
- Max match creations per source IP per minute: **5**.
- Max `action_response` messages per match per second: **2** (well above any sane agent).
- Max concurrent connections per match (across seats and reconnects in grace): **4**.

Exceeding any cap closes the offending connection with `4429`. The same caps apply to malformed
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

**Key payload shapes** (informative summary; the JSON Schemas are authoritative):

- `ObservationRequestPayload`: `{schema_version, match_id, game_id, seat, observation,
  legal_actions}`. `observation` and `legal_actions` are game-specific JSON-safe data produced by
  the game's `Serializer`.
- `ActionResponsePayload`: `{schema_version, match_id, game_id, seat, action}`. `action` is
  game-specific JSON-safe data accepted by the game's `Serializer.load_action(...)`.
- `DomainErrorPayload`: `{code, message, details}`. `code` is the simulation-layer exception's
  canonical name (e.g. `"illegal_action"`, `"wrong_player"`, `"game_finished"`,
  `"invalid_config"`); `details` carries arbitrary JSON-safe metadata.
- `TurnRecordPayload`: `{turn_index, seat, action, events, post_snapshot}` mirroring
  `arena.match.TurnRecord`. `post_snapshot` is a full game-specific snapshot envelope.
- `SnapshotPayload`: `{schema_version, game_id, state, terminal, result}` from
  `Serializer.dump_snapshot(...)`. Required to rehydrate.
- `ResultPayload`: `{kind: "win"|"draw", winner_seat, ...}` mirroring `arena.core.results`.
- `AbortMetadataPayload`: `{reason, message, cause_type, cause_message}` from
  `arena.runtime.AbortMetadata`. `reason` is one of the documented runtime abort codes
  (e.g. `peer_disconnected`, `turn_deadline_expired`, `adapter_error`, `user_quit`).
- `RuntimeEventPayload`: `{event_scope: "runtime", event_type, ...event-specific fields}`.

## 18. Message broadcast matrix

Who receives each Server → Client message in v1 (no spectators) and the reserved v2 expansion:

| Message type        | Active seat | Inactive seat | v2 spectators (reserved) |
|---------------------|-------------|---------------|--------------------------|
| `welcome`           | recipient only (response to that seat's `hello`) | recipient only | recipient only |
| `match_state`       | yes         | yes           | yes                      |
| `observation_request` | **yes (only)** | no         | no (server may emit a redacted copy in v2) |
| `action_rejected`   | **yes (only)** | no          | no                       |
| `turn_committed`    | yes         | yes           | yes                      |
| `match_finished`    | yes         | yes           | yes                      |
| `match_aborted`     | yes         | yes           | yes                      |
| `ping` / `pong`     | per-connection (independent of seat activity) | per-connection | per-connection |
| `error`             | per-connection (only the offending peer) | per-connection | per-connection |

Notes:

- "Inactive seat" includes seats currently in their disconnect grace period that later reconnect:
  the missed broadcasts are reconstructed via transcript replay on resume (§11).
- v1 has no spectator path; the column documents the contract a v2 spectator implementation must
  honor, ensuring v1 message semantics are not broken when spectators are added.
- `match_state` is the **only** lifecycle-transition signal; SDKs should drive their internal
  state machine off it rather than off `welcome.lifecycle` after the initial handshake.
