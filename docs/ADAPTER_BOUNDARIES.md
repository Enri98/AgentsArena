# Adapter Boundary Design

This document defines the intended boundary between the pure simulation/local match code and future
adapter infrastructure. It is a design checkpoint only; it does not introduce adapter code.

## Current Stable Core

The current reusable surface is:
- `arena.core`: pure game abstractions, typed domain exceptions, serializers, results, and registry
- `arena.games`: built-in deterministic perfect-information games
- `arena.match`: pure local match execution, transcript dump/load/validation, and in-process policies

These packages must stay free of transport, persistence, process management, UI, auth, deadlines, and
matchmaking concerns.

## Future Adapter Direction

Future adapters should live outside `arena.core` and `arena.games`. A likely package boundary is:
- `arena.adapters`: optional adapter contracts and implementations
- `arena.adapters.local`: local process/in-memory adapters, if needed
- `arena.adapters.transport`: future protocol-specific adapters, if introduced later

Adapters may depend on `arena.core`, `arena.games`, and `arena.match`. The reverse dependency is not
allowed.

## Adapter Inputs

Adapters should consume existing boundary-safe objects instead of reaching into game internals:
- registered `GameDefinition` objects
- game config payloads validated by game serializers
- observations produced by `rules_engine.observation(...)`
- actions loaded through game serializers
- local match transcripts produced by `dump_match_transcript(...)`
- domain exceptions raised by rules engines and serializers

Adapters should not mutate domain state or construct game-specific state dictionaries by hand.

## Adapter Outputs

Adapters should return or emit explicit boundary payloads:
- serialized observations, actions, configs, snapshots, or transcripts
- domain exception metadata, preserving `code`, `message`, and `details`
- adapter-specific status only at the adapter boundary

Adapter-specific statuses must not be added to `arena.core` result types. Examples that belong only at
the adapter layer include disconnected agents, stale submitted state, timed-out moves, and rejected
credentials.

## Deferred Concerns

The following remain out of scope until an implementation plan section explicitly introduces them:
- HTTP or WebSocket APIs
- remote agent protocols
- subprocess management
- persistent transcript storage
- clocks, deadlines, and timeout outcomes
- authentication and authorization
- matchmaking and tournament scheduling
- UI render payloads

## First Safe Implementation Slice

When adapter work begins, the first implementation should be narrow and reversible:
- define adapter-facing payload models without adding network or storage code
- keep payload conversion at the boundary by delegating to existing serializers
- add contract tests proving adapters do not import from or modify `arena.core` and `arena.games`
- preserve domain exceptions instead of translating them into transport errors inside simulation code

Do not add a server, database, remote process runner, timeout system, or matchmaking layer in the first
adapter slice.

## Phase 28 Slice: `arena.adapters.websocket`

A second adapter, `arena.adapters.websocket`, is planned as a sibling of `arena.adapters.in_process`. It owns the typed wire-envelope contract documented in `docs/NETWORK_PROTOCOL.md`.

Allowed:
- Pydantic v2 envelope models per protocol message type
- discriminated-union message-type validation
- pure JSON encode/decode helpers (`dumps`, `loads`)
- re-export of `arena.adapters.in_process.ObservationRequestPayload`, `ActionResponsePayload`, and `DomainErrorPayload` as the bodies of `observation_request`, `action_response`, and `action_rejected`

Not allowed:
- importing `websockets`, `aiohttp`, `httpx`, FastAPI, or stdlib networking
- performing any I/O (sending or receiving frames)
- holding mutable connection state
- enforcing timeouts, heartbeats, or rate limits (those live in `arena.server`)
- any reference to `arena.server`, `arena.sdk`, `arena.runtime`, `arena.ui`, `arena.cli`

`arena.adapters.websocket` may import `arena.core` (for serializer-derived types) and `arena.adapters.in_process` (for the payload bodies). Nothing in `arena.core`, `arena.games`, `arena.match`, `arena.runtime`, or `arena.ui` may import it.

The server (`arena.server`) and SDK (`arena.sdk`) both depend on `arena.adapters.websocket` so the wire shape stays single-sourced.

## Implemented Phase 18 Slice

The first adapter slice is `arena.adapters.in_process`.

It provides:
- `ObservationRequestPayload`
- `ActionResponsePayload`
- `DomainErrorPayload`
- `InProcessAgent`
- `TypedPayloadPolicyAdapter`
- `build_observation_request(...)`
- `load_action_response(...)`
- `apply_payload_policy_turn(...)`
- `dump_domain_error(...)`

This adapter boundary remains in-process and payload-oriented. It does not add networking,
subprocesses, persistence, timeouts, auth, matchmaking, or UI payloads.

`TypedPayloadPolicyAdapter` is a convenience wrapper over the same payload contract. It loads typed
observations and dumps typed actions through the game serializer, but it still plugs into
`apply_payload_policy_turn(...)` rather than introducing a second match runner.
