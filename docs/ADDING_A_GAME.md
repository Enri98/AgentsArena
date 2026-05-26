# Adding a New Game

AgentsArena v1 supports deterministic, perfect-information, sequential, 2-seat
games. Any new game in v1 must respect those constraints. Stochasticity,
imperfect information, more than two seats, and simultaneous moves are explicit
v2 work — see `docs/RFC_IMPERFECT_INFORMATION.md` and the "Deferred to v2"
section of `CLAUDE.md`.

The work splits cleanly across one core game package and three per-layer
adapter modules. Each adapter layer maintains its own self-registering registry
(`arena.cli.games._registry`, `arena.agents.ollama._adapters`,
`arena.mcp._adapters`); there is no longer a central dispatch table to edit.
Nim (`src/arena/games/nim/`) is the cleanest exemplar and is referenced
throughout — read it alongside this guide.

## Checklist

Create these files, in order:

- [ ] `src/arena/games/<name>/__init__.py`
- [ ] `src/arena/games/<name>/config.py`
- [ ] `src/arena/games/<name>/state.py`
- [ ] `src/arena/games/<name>/actions.py`
- [ ] `src/arena/games/<name>/observation.py`
- [ ] `src/arena/games/<name>/events.py`
- [ ] `src/arena/games/<name>/rules.py`
- [ ] `src/arena/games/<name>/serializer.py`
- [ ] `src/arena/games/<name>/definition.py`
- [ ] One edit to `src/arena/games/__init__.py` (register in default registry)
- [ ] `src/arena/cli/games/<name>.py` + one edit to `src/arena/cli/games/__init__.py`
- [ ] `src/arena/agents/ollama/<name>.py` + one edit to `src/arena/agents/ollama/__init__.py`
- [ ] `src/arena/mcp/games/<name>.py` + one edit to `src/arena/mcp/games/__init__.py`
- [ ] `tests/unit/games/<name>/` (config, rules, serializer)
- [ ] `tests/contract/test_<name>_contract.py`
- [ ] `tests/integration/test_<name>_happy_path.py`

## 1. The game package (`arena.games.<name>`)

The simulation core is pure: frozen dataclasses for in-memory state, Pydantic
v2 for boundary payloads, integer seats only, no I/O. The nine files below are
the canonical split — Nim is the reference (`src/arena/games/nim/`).

### `config.py`

A single `BaseGameConfig` subclass. Pydantic v2 with `Field` constraints. No
behaviour, only validated parameters.

```python
class MyConfig(BaseGameConfig):
    rows: int = Field(default=8, ge=2)
```

See `src/arena/games/nim/config.py`.

### `state.py`

The minimal authoritative state as a `@dataclass(frozen=True)`. Validate
invariants in `__post_init__`. Store only what cannot be derived; legality,
terminality, and winners are computed on demand by the rules engine.

```python
@dataclass(frozen=True)
class MyState:
    board: tuple[tuple[int, ...], ...]
    current_seat: Seat
```

See `src/arena/games/nim/state.py`.

### `actions.py`

One or more frozen `Action` subclasses. Validate field shapes in
`__post_init__`; defer legality to the rules engine.

```python
@dataclass(frozen=True)
class MyMove(Action):
    column: int
```

See `src/arena/games/nim/actions.py`.

### `observation.py`

A frozen `Observation` subclass carrying the public per-seat view plus
`legal_actions: tuple[ActionT, ...]`. Inherits `seat: Seat` from
`arena.core.observations.Observation`.

See `src/arena/games/nim/observation.py`.

### `events.py`

`DomainEvent` subclasses emitted by successful transitions. Keep payloads
JSON-friendly (use `list[int]` not `tuple[int, ...]` for fields that will be
serialized as-is in tests/transcripts; the runtime envelopes do not coerce
these for you).

See `src/arena/games/nim/events.py`.

### `rules.py`

The `RulesEngine` implementation. Must satisfy the protocol in
`src/arena/core/rules_engine.py`:

- `initial_state(config) -> StateT`
- `current_seat(state) -> Seat`
- `legal_actions(state, seat) -> tuple[ActionT, ...]`
- `validate_action(state, seat, action) -> None` — raise `WrongPlayer`,
  `IllegalAction`, or `GameFinished` from `arena.core.exceptions`
- `apply_action(state, seat, action) -> TransitionResult[StateT, DomainEvent, RuleResult | None]`
  (call `validate_action` defensively at the top)
- `is_terminal(state) -> bool`
- `result(state) -> RuleResult | None` — must be reconstructible from state alone
- `observation(state, seat) -> ObservationT`

Terminal `result()` must be computable from `state` only — pick a state
convention that encodes the winner (e.g. Nim sets `current_seat` to the mover
on the terminal transition). See `src/arena/games/nim/rules.py`.

### `serializer.py`

A `Serializer` implementation (`src/arena/core/serializer.py`) backed by
Pydantic v2 models with `model_config = ConfigDict(extra="forbid", strict=True)`.
Implements eight `dump_*` / `load_*` methods over config, state, action, and
observation. Every round trip must produce an equal in-memory object.

See `src/arena/games/nim/serializer.py`.

### `definition.py`

Exports `GAME_ID`, a `build_<name>_game_definition()` factory returning a
`GameDefinition`, a module-level instance, and `register_<name>(registry)`.

```python
MY_GAME_ID = "mygame"

def build_my_game_definition() -> GameDefinition[...]:
    return GameDefinition(
        game_id=MY_GAME_ID,
        display_name="MyGame",
        config_type=MyConfig,
        state_type=MyState,
        action_type=MyMove,
        observation_type=MyObservation,
        rules_engine=MyRulesEngine(),
        serializer=MySerializer(),
        result_type=RuleResult,
    )

MyGameDefinition = build_my_game_definition()

def register_my(registry: GameRegistry) -> None:
    registry.register(MyGameDefinition)
```

See `src/arena/games/nim/definition.py`.

### `__init__.py`

Re-export the public surface (`GAME_ID`, config, state, action, observation,
events, rules engine, serializer, definition, `register_<name>`) for stable
imports. See `src/arena/games/nim/__init__.py`.

## 2. Register the game

Add one import and one call inside `register_builtin_games` in
`src/arena/games/__init__.py`:

```python
def register_builtin_games(registry: GameRegistry) -> None:
    from arena.games.connect4.definition import register_connect4
    from arena.games.nim.definition import register_nim
    from arena.games.tictactoe.definition import register_tictactoe
    from arena.games.mygame.definition import register_my

    register_connect4(registry)
    register_tictactoe(registry)
    register_nim(registry)
    register_my(registry)
```

`build_default_registry()` picks it up automatically. Without this edit the
game exists but the server, CLI, and SDK will not see it.

## 3. CLI adapter

Create `src/arena/cli/games/<name>.py` and call `register_cli_adapter` at
module scope. The dataclass (`src/arena/cli/games/_registry.py`) requires all
five fields:

| Field | Type | Nim does |
|-------|------|----------|
| `renderer` | `(state_payload: Mapping) -> str` | ANSI bar chart of pile sizes |
| `plain_renderer` | `(state_payload: Mapping) -> str` | Same chart, no ANSI |
| `human_parser` | `(line: str, observation) -> Action \| None` | Parses `"<pile> <count>"`, returns `None` on bad input or illegal moves |
| `scripted_parser` | `(spec: str) -> list[Action]` | Parses comma-separated `"<pile> <count>"` tokens; raises `ValueError` on bad shape |
| `config_factory` | `(argparse.Namespace) -> BaseGameConfig` | Reads `--nim-piles` / `--nim-pile-size` from `args` |

```python
register_cli_adapter(
    CliGameAdapter(
        game_id=MY_GAME_ID,
        renderer=render_state,
        plain_renderer=render_state_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)
```

Then add `from arena.cli.games import mygame as _mygame  # noqa: F401` to
`src/arena/cli/games/__init__.py` so the registration fires on package import.
Reference: `src/arena/cli/games/nim.py`.

## 4. Ollama adapter

Create `src/arena/agents/ollama/<name>.py`. There is **no** generic
prompt-builder — each game ships a hand-tuned `PromptBuilder` (protocol in
`src/arena/agents/ollama/agent.py`):

- `build_messages(observation, retry_feedback)` — returns `list[dict[str, str]]`
  chat messages; embed legal actions in the user prompt and append rejection
  reasons from `retry_feedback`
- `parse_response(content, observation)` — return the parsed action or `None`
  (illegal or unparseable); the agent's retry loop handles the rest
- `format_spec()` — JSON Schema passed to Ollama's structured-output mode
- `describe_invalid(raw_content)` — short rejection blurb used as retry
  feedback

```python
register_ollama_adapter(
    OllamaGameAdapter(
        game_id=MY_GAME_ID,
        prompt_builder_factory=MyPromptBuilder,
    )
)
```

Add `from arena.agents.ollama.mygame import MyPromptBuilder` to
`src/arena/agents/ollama/__init__.py` so the registration fires before
`_remote` is imported. Reference: `src/arena/agents/nim.py`.

## 5. MCP adapter

Create `src/arena/mcp/games/<name>.py`:

```python
MY_ACTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "column": {"type": "integer", "minimum": 0},
    },
    "required": ["column"],
}

register_mcp_adapter(McpGameAdapter(game_id=MY_GAME_ID, action_schema=MY_ACTION_SCHEMA))
```

The schema is hand-written rather than derived from the action's Pydantic
payload. Auto-derivation was considered and rejected: action-payload models
inherit `extra="forbid"` plus stricter validators than MCP clients can be
expected to satisfy, and any drift in those models would otherwise leak wire
noise to every connected agent. Hand-written keeps the wire surface
intentional.

Then add `from arena.mcp.games import mygame as _mygame  # noqa: F401` to
`src/arena/mcp/games/__init__.py`. Reference: `src/arena/mcp/games/nim.py`.

## 6. Tests

Add, at minimum:

- `tests/unit/games/<name>/test_config.py` — defaults, range validation,
  `extra="forbid"` enforcement (pattern: `tests/unit/games/nim/test_config.py`)
- `tests/unit/games/<name>/test_rules.py` — initial state, legality,
  terminal/winner derivation, defensive validation in `apply_action`
- `tests/unit/games/<name>/test_serializer.py` — round-trip every payload
- **`tests/contract/test_<name>_contract.py`** — must-add minimum. Wrap your
  definition in a `GameContractBundle` and run `assert_game_contract(...)` from
  `arena.testing`. This is the single test that proves the new game is wired
  end-to-end. See `tests/contract/test_nim_contract.py`.
- `tests/integration/test_<name>_happy_path.py` — drive a full match against a
  running `arena.server` via real WebSocket frames. Pattern:
  `tests/integration/test_nim_happy_path.py`.

Add CLI / Ollama / MCP-layer tests beside the existing per-game ones in
`tests/unit/cli/`, `tests/unit/agents/ollama/`, and `tests/unit/mcp/`.

## 7. Verification

From the activated `.venv`:

```bash
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe -q
```

After committing, re-run `npx gitnexus analyze` (preserve embeddings with
`--embeddings` if `.gitnexus/meta.json` shows a non-zero `stats.embeddings`).
The PostToolUse hook handles this automatically on Claude Code sessions. Per
`CLAUDE.md`, run `gitnexus_impact` on any symbol you intend to modify and
`gitnexus_detect_changes()` before committing.

## Common pitfalls

- **Forgetting `register_builtin_games`.** The game package can be fully
  written, imported, and unit-tested while remaining invisible to the server,
  CLI, SDK, and MCP layers. The contract test will pass; the integration test
  will fail with `KeyError` from the registry.
- **Forgetting the per-layer `__init__.py` edit.** Each of
  `arena.cli.games/__init__.py`, `arena.agents.ollama/__init__.py`, and
  `arena.mcp.games/__init__.py` is the **only** place where per-game adapter
  modules are imported, and registration is a side-effect of that import. Skip
  the edit and the registry entry never appears.
- **Layering violations.** Game packages may not import from `arena.cli`,
  `arena.agents`, `arena.mcp`, `arena.server`, `arena.sdk`, `arena.runtime`,
  `arena.ui`, `arena.match`, or `arena.adapters`. The architecture tests in
  `tests/unit/architecture/` will fail loudly.
- **Scripted-parser vs human-parser drift.** Both parse user-supplied move
  strings; keep their tokenisation aligned or scripted runs will reject moves
  that the interactive driver accepts. Nim uses `"<pile> <count>"` in both.
- **Terminal state that cannot reconstruct the winner.** `result(state)` must
  return the winner from `state` alone (no engine-side bookkeeping). Either
  encode the mover in `current_seat` on the terminal transition (Nim's
  approach) or carry an explicit terminal marker in state.
- **Mutating events with non-JSON-native fields.** Use `list[int]`, not
  `tuple[int, ...]`, for event fields that are dumped verbatim; transcripts
  validate strictly. See `NimObjectsTaken.remaining`.
- **`schema_version` drift.** Runtime payloads pin `schema_version=1`. New
  games inherit this; bumping it is an explicit, separate change.

## Out of scope for v1

- Stochasticity (random draws, dice, shuffled decks)
- Imperfect information (hidden hands, private state)
- More than two seats
- Simultaneous moves

These require schema, runtime, and protocol changes covered in
`docs/RFC_IMPERFECT_INFORMATION.md`. See also the "Deferred to v2" section of
`CLAUDE.md`.
