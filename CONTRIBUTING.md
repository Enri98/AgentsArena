# Contributing to AgentsArena

## Set up

Python 3.11 and, for the TypeScript SDK, Node 22.18+ (CI uses Node 24).

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev,mcp]"
```

Always work inside the virtual environment.

## Check your change

```bash
ruff check .
mypy                          # configured in pyproject.toml; the package ships py.typed
pytest -q                     # about 1,400 tests; a hung test fails after 120 s
cd sdk-ts && npm ci && npm run typecheck && npm test   # if you touched sdk-ts/
```

CI runs the same steps on every pull request (`.github/workflows/ci.yml`).

**Tests that reach the network stack cannot catch entry-point bugs.** After changing
`arena.server`, the SDKs or the wire protocol, also run the real stack: start
`python -m arena.server`, then play a match with `examples/run_remote_demo.py` (local
Ollama) or `node sdk-ts/examples/play_match.ts http://127.0.0.1:8080 rps`.

## Rules the code keeps

`CLAUDE.md` and `AGENTS.md` have the full list. The ones most often broken:

- **Layers only import downward.** `docs/ADAPTER_BOUNDARIES.md` has the table, and the
  architecture tests in `tests/unit/architecture/` enforce it.
- **The simulation core is pure:** frozen dataclasses, no I/O, integer seats.
  `apply_action` revalidates everything it is given.
- **Everything sent to a viewer is built for that viewer.** Never send a full state or a
  full transcript to a client.
- **Never put a random seed in config or state.** Both are broadcast.
- **`docs/NETWORK_PROTOCOL.md` is the wire contract.** A change to what goes on the wire
  updates the spec in the same pull request, and an incompatible change bumps
  `schema_version` (§7). `GET /schemas/payloads` is pinned per version by a golden file.
- **Deadlines, heartbeats and rate limits live in `arena.server` only.**

## WebSocket tests

- One live WebSocket per Starlette `TestClient` test. Anything needing two sockets belongs
  in `tests/integration/`, which runs a real uvicorn server over TCP (`running_server`).
- Always use `with TestClient(app) as client:`.
- Pass short `per_turn_deadline_ms` and `disconnect_grace_ms` so an abandoned match does not
  park for 30 s.

## Adding a game

Start from the scaffold (`python -m arena.games.scaffold --name mygame --kind hidden`) and
follow `docs/ADDING_A_GAME.md`. A game is done when its contract test (the shared suite in
`arena.testing`) passes and it plays over the real server.

## Pull requests

- Keep a pull request to one coherent change, with tests beside the code.
- Update `CHANGELOG.md` under `[Unreleased]` for anything a user of the library, the server
  or the protocol would notice.
- Large features go through an adversarial review before merging: a reviewer (human or
  agent) tries to break the change, and confirmed findings are fixed with tests first.

## Releasing

1. Move the `[Unreleased]` entries in `CHANGELOG.md` under a new version heading.
2. Bump the version in `pyproject.toml`, `sdk-ts/package.json` and `CLIENT_VERSION` in
   `sdk-ts/src/protocol.ts` together: both packages release under the same version, and the
   release workflow refuses a tag that does not match all of them.
3. Tag `vX.Y.Z` on a commit of `main` and push the tag. The release workflow builds and checks the
   distributions and attaches them to a GitHub release.
