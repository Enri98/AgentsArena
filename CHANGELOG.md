# Changelog

All notable changes to AgentsArena. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/). The wire protocol has its own
`schema_version`, listed with each release; `docs/NETWORK_PROTOCOL.md` Appendix A has its history.

## [Unreleased]

## [0.2.0] - 2026-09-25

The v2 roadmap (Phases 36-42). Wire `schema_version` 4; decoders accept 1-4.

### Added

- **Spectators** (Phase 36): `WS /matches/{id}/spectate`, with `spectator_hello` /
  `spectator_welcome`, bounded per-connection outbound queues so a slow spectator cannot
  stall a match, and a zero-dependency browser viewer (`examples/spectator/`).
- **Rate limits** (Phase 36, protocol §13): connections per IP, spectators per match,
  WebSocket opens and transcript reads per IP per minute.
- **Chance nodes** (Phase 37, wire v2): nature's moves drawn from a generator the match owns
  (never in config or state), recorded as `kind: "chance"` transcript turns and replayed
  without the seed. Pig is the exemplar.
- **Hidden information** (Phase 38, wire v3): per-seat and public views of state, events,
  chance outcomes and transcripts; everything sent to a viewer is built for that viewer.
- **Liar's Dice** (Phase 39): hidden information plus chance, proven over the wire and with
  local Ollama agents.
- **Transcript persistence** (Phase 40): public transcripts of ended matches kept in memory,
  in files or in SQLite with retention limits, and served by
  `GET /matches/{id}/public-transcript`.
- **Simultaneous moves** (Phase 41, wire v4): joint turns (`kind: "joint"` with an
  `actions` map) where every acting seat is asked at once, each with its own deadline,
  retries and grace. Rock-Paper-Scissors is the exemplar.
- **TypeScript SDK** (Phase 42): `sdk-ts/`, `@agents-arena/sdk`, on the standard
  `WebSocket` and `fetch`: `playMatch`, `SeatSession`, `spectate`, `createMatch`,
  `fetchPublicTranscript`.
- **Scaffold kinds** (Phase 42): `python -m arena.games.scaffold --kind
  chance|hidden|simultaneous` generates a working game of that kind, with adapters and a
  contract test.
- A golden-file test pins `GET /schemas/payloads` per wire version.
- `--public-url` / `ARENA_PUBLIC_URL`: the server's public address, on which seat URLs are built
  (`wss://` behind a TLS-terminating proxy).
- Packaging: console scripts (`arena-server`, `arena-play`, `arena-replay`, `arena-mcp`,
  `arena-scaffold`) that name the extra to install when one is missing, a `client` extra for the
  Python SDK, `arena.__version__`, PEP 561 `py.typed`, project URLs and classifiers.
- CI (GitHub Actions): ruff, mypy, the TypeScript SDK's type-check and tests, pytest, and a job that
  builds the distributions and smoke-tests the installed wheel. A release workflow builds both
  packages on a `v*` tag and attaches them to a GitHub release; publishing is opt-in.
- `CONTRIBUTING.md`, `SECURITY.md`, this changelog, Dependabot and a pre-commit config.

### Changed

- Every wire and runtime payload is at `schema_version` 4.
- The match driver is owned by the match, not by a seat's connection.
- Connections refused before `hello` (unknown match, bad seat, rate limited) now read the
  client's first frame before closing, so every client sees the close code.
- `match_finished.result`, `match_state.result` and `GET /matches/{id}` `result` carry the
  result of a finished match; they used to be empty.
- A seat that stops reading is closed `1013` (and may resume) instead of silently losing frames;
  a seat sending more than 16 malformed frames in a turn is closed `4422`.
- Seat URLs are `wss://` for requests over https.
- `docs/NETWORK_PROTOCOL.md` is consolidated at v4, with superseded shapes in appendices.
- The server disables WebSocket permessage-deflate (it broke Node's client).

### Security

- A running match refuses a token-less `hello` for a seat (4409); a seat moves only with its
  resume token.
- The per-turn deadline is absolute: reconnecting does not extend it.
- Only the right-most entry of the configured trusted proxy header is used for the client IP;
  IPv6 clients are bucketed per /64.
- Request bodies, frames, player counts and labels are bounded.

## [0.1.0] - 2026-05-23

The v1 milestone (Phases 0-35). Wire `schema_version` 1.

### Added

- Simulation core: typed immutable domain objects, `GameDefinition`, `RulesEngine`,
  `Serializer`, `Registry`, typed domain exceptions, and a shared game contract suite.
- Games: Connect 4, Tic-Tac-Toe and Nim.
- Local matches, transcripts (dump, load, validate), in-process policies.
- In-process and WebSocket adapter payload contracts.
- Runtime coordinator (`Arena`, `MatchSession`), UI adapter, terminal renderer, replay
  viewer and interactive CLI (`python -m arena.cli.play`) with human, scripted and Ollama
  seats.
- Local Ollama agents with retry-with-feedback.
- WebSocket server (`python -m arena.server`) with per-turn deadlines, heartbeats,
  disconnect grace, resume tokens and structured JSON logs; a Dockerfile and a Fly.io
  recipe.
- Reference Python SDK (`arena.sdk`) and an MCP server (`arena.mcp`, stdio and HTTP/SSE).
- `docs/NETWORK_PROTOCOL.md`, the language-agnostic wire specification.

