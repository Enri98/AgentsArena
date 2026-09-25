# Adapter Boundaries

How the layers above the simulation core talk to it, and what each may import. The import
rules below are enforced by the architecture tests in `tests/unit/architecture/`; when this
document and those tests disagree, the tests win and this document is wrong.

## The layers

| Layer | Package | May import (within `arena`) |
|-------|---------|------------------------------|
| Simulation core | `arena.core` | nothing above it |
| Games | `arena.games.*` | `arena.core` |
| Local match | `arena.match` | `arena.core`, `arena.games` |
| In-process adapter | `arena.adapters.in_process` | `arena.core`, `arena.match` (not `arena.runtime`) |
| WebSocket adapter | `arena.adapters.websocket` | `arena.core`, `arena.adapters.in_process` (payload bodies), `arena.runtime.payloads` |
| Runtime | `arena.runtime` | `arena.core`, `arena.match`, `arena.adapters.in_process` (not `arena.adapters.websocket`) |
| UI adapter | `arena.ui` | `arena.runtime` only |
| CLI | `arena.cli` | `arena.core`, `arena.games`, `arena.adapters.in_process`, `arena.runtime`, `arena.ui`, `arena.agents`, and `arena.sdk` for `--server-url` |
| Local agents | `arena.agents.ollama` | `arena.core`, `arena.games`, `arena.cli` (board renderers, the remote-seat helper); not `match`, `adapters`, `runtime`, `ui` |
| Server | `arena.server` | everything below it except `arena.sdk` and `arena.cli` |
| Python SDK | `arena.sdk` | `arena.core`, `arena.games`, `arena.adapters.websocket` (not `match`, `adapters.in_process`, `runtime`, `ui`, `cli`, `server`) |
| MCP server | `arena.mcp` | `arena.sdk`, `arena.core`, `arena.games` |
| Contract suite | `arena.testing` | `arena.core`, `arena.match` |

No layer imports a layer above it: nothing below `arena.server` imports it, nothing below
`arena.sdk` imports the SDK, and nothing imports `arena.mcp`. Only `arena.server` creates
loggers at module scope. The TypeScript SDK (`sdk-ts/`) shares no code with the Python
packages: it speaks the wire protocol in `docs/NETWORK_PROTOCOL.md` and nothing else.

## What crosses a boundary

Adapters consume boundary-safe objects, never game internals:

- registered `GameDefinition` objects, looked up through a `GameRegistry`;
- configs, actions, observations, states and chance outcomes, loaded and dumped only through
  the game's `Serializer`;
- local match transcripts from `dump_match_transcript` (the full view) or
  `dump_match_transcript_for_viewer` (a seat's or the public's);
- domain exceptions (`ArenaCoreError` subclasses), whose `code`, `message` and `details` are
  preserved as `DomainErrorPayload`.

Adapters never mutate domain state or build game-specific state dictionaries by hand.

**Everything sent to a viewer is built for that viewer** (Phase 38). A viewer is a seat or
`None`, the public. For a hidden-information game only the server holds the full transcript;
a seat receives `view: "seat"` payloads and a spectator `view: "public"`. Use the
`*_for_viewer` helpers in `arena.core.public_view`, `arena.match` and `arena.runtime`; never
send `dump_state`, `_build_snapshot` or `dump_match_transcript` output to a client directly.

Adapter-specific outcomes stay at the adapter layer, never in `arena.core` result types:
disconnected agents, missed deadlines, rejected credentials and rate limits are runtime aborts
or wire close codes.

## `arena.adapters.in_process`

The serialized payload contract for agents that run in the same process:

- `ObservationRequestPayload`, `ActionResponsePayload`, `DomainErrorPayload`;
- `build_observation_request(match, seat=None)` and `load_action_response(...)`;
- `apply_payload_policy_turn(...)` for a sequential turn and
  `apply_payload_policy_joint_turn(...)` for a simultaneous round (Phase 41), which asks every
  acting seat from its own observation before applying the round;
- `dump_domain_error(...)`;
- `TypedPayloadPolicyAdapter` and `InProcessAgent`, which load typed observations and dump
  typed actions through the game serializer.

It adds no networking, subprocesses, persistence, deadlines, auth or UI payloads.

## `arena.adapters.websocket`

The typed wire-envelope contract: Pydantic v2 envelope models per message type, a
discriminated union over message types, and pure `dumps` / `loads` helpers. The bodies of
`observation_request`, `action_response` and `action_rejected` are the in-process payloads,
reused verbatim, and transcripts ride inside `welcome`, `spectator_welcome`,
`match_finished` and `match_aborted` as `arena.runtime.payloads` models.

It performs no I/O, holds no connection state, and imports no networking library. Deadlines,
heartbeats and rate limits live in `arena.server`. The server and the Python SDK both depend
on it, so the wire shape has one source.

## `arena.runtime` and `arena.ui`

`arena.runtime` coordinates matches in memory (`Arena`, `MatchSession`, lifecycle, runtime
events, aborts) and produces the JSON-safe `dump_session_status` / `dump_runtime_transcript`
payloads, each with an optional `viewer`. It stays deadline-free: wall-clock timeouts exist
only in the server, which turns an expired deadline into an ordinary runtime abort
(`turn_deadline_expired`).

`arena.ui` reshapes runtime payloads into screen-level payloads (`build_match_status`,
`build_match_transcript`, `build_match_screen`). It exposes `state_payload` from snapshots
and never recomputes rules.

## Per-game adapter registries

The CLI (`arena.cli.games`), the Ollama agents (`arena.agents.ollama._adapters`) and MCP
(`arena.mcp.games`) each keep a registry that per-game modules register into at import time.
A new game registers with each layer's registry; no layer grows an `if game_id == ...`
branch. `docs/ADDING_A_GAME.md` walks through it, and
`python -m arena.games.scaffold --kind ...` generates all three adapters.
