# IMPLEMENTATION_PLAN.md

## 1. Document purpose

This document defines the technical implementation plan for the Python simulation library that will power a future agent arena. 

The document describes:
- the target architecture
- the module boundaries
- the implementation sequence
- the validation and testing strategy
- the acceptance criteria for each milestone
- the deferred concerns that are out of scope for the current phase

## 2. Project objective

The objective of the first implementation phase is to build a reusable, pure simulation package for deterministic, sequential, perfect-information games, starting with Connect 4.

The package should provide:
- strongly typed in-memory domain models
- validated configuration models
- reusable game abstractions
- explicit legal action generation and validation
- pure state transitions
- rule-based terminal/result logic
- domain event emission
- JSON-friendly serialization at the boundary
- state snapshot rehydration
- a manual game registry
- a shared generic test contract for all games

The first phase should not include network APIs, a database layer, UI code, agent connectivity, or orchestration-specific concerns.

## 3. Architecture summary

The system is divided into three conceptual layers, but only the first is implemented in this phase.

### 3.1 Simulation layer

Implemented now.

Responsibilities:
- game metadata and configuration
- state, action, observation, and result abstractions
- rules evaluation
- legal action production
- action validation
- state transition application
- terminal state and result calculation
- domain event generation
- serialization and rehydration

### 3.2 Match / arena layer

Deferred.

Future responsibilities:
- match lifecycle
- seat assignment to agents
- state versioning and stale move protection
- deadlines and timeouts
- persistent event logs and snapshots
- replay feeds
- UI payloads

### 3.3 Adapters / transport layer

Deferred.

Future responsibilities:
- REST / WebSocket APIs
- agent protocol adapters
- UI-facing rendering payloads
- persistence adapters

## 4. Guiding design decisions

These decisions are fixed for the current phase.

### 4.1 Scope constraints

Version 1 supports only:
- sequential turns
- deterministic rules
- perfect information

The design should avoid blocking future support for:
- hidden information
- chance nodes
- simultaneous actions
- multi-stage turn resolution

### 4.2 Model technology

Use two complementary model styles.

#### 4.2.1 Domain objects

Use **frozen dataclasses** for in-memory domain state and actions.

Rationale:
- they fit pure, immutable-ish state transitions
- they are lightweight and explicit
- Python dataclasses support frozen instances and hash generation when `eq=True` and `frozen=True`, which supports read-only domain modeling well. ([Python docs](https://docs.python.org/3/library/dataclasses.html))

#### 4.2.2 Boundary-facing models

Use **Pydantic v2** for configuration and serialization-facing models.

Rationale:
- Pydantic validates typed models efficiently
- Pydantic supports both Python-mode and JSON-mode serialization
- Pydantic can emit JSON Schema via `model_json_schema()` and `TypeAdapter.json_schema()`
- strict typed schemas will be useful later for agent-facing contracts and API payloads. ([Pydantic docs](https://docs.pydantic.dev/latest/concepts/serialization/)) ([Pydantic docs](https://docs.pydantic.dev/latest/concepts/json_schema/))

### 4.3 Internal vs external representation

The simulation core uses typed Python objects internally. JSON is a serialization boundary only.

### 4.4 State philosophy

Store only minimum authoritative state. Derive convenience fields on demand.

Examples of derived values:
- whether the game is terminal
- winner
- legal actions
- human-readable render payloads

### 4.5 Validation philosophy

`apply_action(...)` must be defensive and re-check legality.

Validation should exist both as:
- explicit validation routines
- enforced checks inside state transitions

### 4.6 Identity model

The simulation core knows only seat identifiers, represented as integers.

Examples:
- `0`
- `1`

Human-readable agent names belong to future adapter layers.

### 4.7 Serialization philosophy

Every successful move must produce a full serialized post-move snapshot. The initial state must also be serializable and stored as a snapshot. Snapshots must be rehydratable into real in-memory state objects.

### 4.8 Error boundary

The simulation layer raises only pure domain exceptions.

Included examples:
- invalid config
- wrong player
- illegal action
- game already finished
- serialization / rehydration errors

Excluded examples:
- stale state version
- deadline exceeded
- disconnected agent
- authentication failure

### 4.9 Registration model

Games are registered manually through a central registry.

### 4.10 Observation model

A distinct Observation abstraction exists from the beginning, even if the Connect 4 observation initially mirrors public state.

### 4.11 Event model

The simulation layer emits domain events for successful transitions and rule outcomes.

Examples for Connect 4:
- `DiscDropped`
- `WinnerDetected`
- `GameDrawn`

## 5. Reference concepts informing the design

The design intentionally borrows only the useful ideas from existing libraries.

### 5.1 PettingZoo influence

PettingZoo’s AEC model is a good reference for sequential turn-taking and legal-action exposure. The current project does not adopt PettingZoo directly, but it borrows the idea that the environment always knows whose turn it is and what actions are legal. ([PettingZoo docs](https://pettingzoo.farama.org/index.html))

### 5.2 OpenSpiel influence

OpenSpiel is a reference for the compact interface shape: current player, legal actions, apply action, terminal state, observation / information state, and serializable state. The current project uses these ideas without importing OpenSpiel itself. ([OpenSpiel docs](https://openspiel.readthedocs.io/en/latest/concepts.html))

### 5.3 AGENTS.md usage

`AGENTS.md` is intentionally short because Codex reads AGENTS files before starting work and layers them from broader scope to narrower scope. The detailed project source of truth therefore belongs in this implementation plan, not in AGENTS alone. ([OpenAI Codex docs](https://developers.openai.com/codex/guides/agents-md)) ([OpenAI Codex Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide/))

## 6. Target package structure

A recommended starting structure is:

```text
AgentsArena/
  pyproject.toml
  AGENTS.md
  IMPLEMENTATION_PLAN.md
  src/
    arena/
      __init__.py
      core/
        __init__.py
        types.py
        seats.py
        exceptions.py
        events.py
        actions.py
        observations.py
        results.py
        game_definition.py
        rules_engine.py
        serializer.py
        registry.py
        config.py
      games/
        __init__.py
        connect4/
          __init__.py
          config.py
          state.py
          actions.py
          observation.py
          events.py
          result.py
          rules.py
          serializer.py
          definition.py
      testing/
        __init__.py
        contracts.py
        factories.py
  tests/
    unit/
      core/
      games/
        connect4/
    contract/
      test_game_contract.py
```

The exact filenames may vary slightly, but the separation of responsibilities should remain.

## 7. Core module responsibilities

## 7.1 `arena.core.types`

Purpose:
- shared aliases and low-level type definitions

Likely contents:
- `Seat = int`
- small shared value aliases if needed
- serialization helper types for JSON-compatible structures

This module should remain small.

## 7.2 `arena.core.seats`

Purpose:
- seat-related helper logic and validation rules

This module may remain minimal in v1, but is useful to keep identity handling centralized.

## 7.3 `arena.core.exceptions`

Purpose:
- define domain-level exceptions for the pure simulation package

Candidate exception hierarchy:
- `ArenaCoreError`
- `ConfigError`
- `InvalidGameConfig`
- `RulesError`
- `WrongPlayer`
- `IllegalAction`
- `GameFinished`
- `SerializationError`
- `RehydrationError`
- `UnknownGame`
- `DuplicateGameRegistration`

Exception payload expectations:
- machine-readable error code
- human-readable message
- optional structured details

## 7.4 `arena.core.events`

Purpose:
- define the shared domain event abstraction

Expected design:
- a base frozen dataclass or protocol for domain events
- event name / event type identifier
- associated seat where relevant
- event payload or strongly typed fields

Event objects should remain pure simulation-domain objects, not persistence records.

## 7.5 `arena.core.actions`

Purpose:
- define the base action abstraction

Expected design:
- actions do not embed the acting seat
- actions are pure move objects
- concrete games define their own action subtypes

## 7.6 `arena.core.observations`

Purpose:
- define the observation abstraction and any shared observation-facing serializer types

Version 1 expectation:
- the abstraction exists even if Connect 4 exposes the full public state

## 7.7 `arena.core.results`

Purpose:
- define rule-based outcome types

Expected scope:
- win
- draw
- ongoing / non-terminal helper types if needed

Orchestration-specific outcomes stay outside this layer.

## 7.8 `arena.core.config`

Purpose:
- define shared config model behaviors and conventions

Expected design:
- Pydantic base config model
- forbid unknown fields
- common metadata fields if needed, such as config version

## 7.9 `arena.core.game_definition`

Purpose:
- define the static metadata and wiring contract for a game

Expected responsibilities:
- stable game identifier
- display name
- config model type
- state type
- action type family
- observation type
- result type
- rules engine factory or reference
- serializer factory or reference

This object should be the registry-facing entry point for a game.

## 7.10 `arena.core.rules_engine`

Purpose:
- define the rules contract that each concrete game must implement

Expected interface shape:
- create initial state
- compute current seat
- compute legal actions
- validate action
- apply action
- detect terminal state
- compute result
- build observation

A possible shape:

```python
class RulesEngine(Protocol):
    def initial_state(self, config: BaseGameConfig) -> GameState: ...
    def current_seat(self, state: GameState) -> int: ...
    def legal_actions(self, state: GameState, seat: int) -> tuple[Action, ...]: ...
    def validate_action(self, state: GameState, seat: int, action: Action) -> None: ...
    def apply_action(self, state: GameState, seat: int, action: Action) -> TransitionResult: ...
    def is_terminal(self, state: GameState) -> bool: ...
    def result(self, state: GameState) -> RuleResult | None: ...
    def observation(self, state: GameState, seat: int) -> Observation: ...
```

`TransitionResult` is discussed below.

## 7.11 `arena.core.serializer`

Purpose:
- define serializer and rehydration contracts

Expected responsibilities:
- serialize config to boundary payload
- rehydrate config from payload
- serialize state snapshot
- rehydrate state snapshot
- serialize actions
- rehydrate actions
- serialize observations where useful
- emit JSON Schema for boundary-facing models

The serializer should be per-game, but the interface should be shared.

## 7.12 `arena.core.registry`

Purpose:
- central manual registration and lookup of games

Responsibilities:
- register a `GameDefinition`
- reject duplicate identifiers
- resolve by game id
- list registered games

This registry is a library concern, not an IoC container.

## 8. Transition model

A successful move should produce more than just a new state. It should return a structured transition result.

Recommended shape:

```python
@dataclass(frozen=True)
class TransitionResult:
    state: GameState
    events: tuple[DomainEvent, ...]
    result: RuleResult | None
```

Rationale:
- the new state is required
- emitted domain events are required
- the rule result is convenient when the transition ends the game

This keeps event emission explicit without leaking persistence concerns into the simulation core.

## 9. Connect 4 concrete design

## 9.1 Game characteristics

Connect 4 in this project is:
- 2-player
- sequential
- deterministic
- perfect-information
- single-phase in v1

## 9.2 Connect 4 config model

Use a Pydantic config model with strict validation and forbidden extra fields.

Version 1 may support:
- `rows: int = 6`
- `columns: int = 7`
- `connect_length: int = 4`

Even if the default variant is the standard game, keeping the config explicit makes the abstraction reusable.

Validation rules should include:
- minimum rows and columns large enough to make the game meaningful
- `connect_length >= 2`
- `connect_length <= max(rows, columns)`
- the standard Connect 4 implementation in v1 is fixed to two seats

## 9.3 Connect 4 state model

State should contain only authoritative minimum data.

Recommended fields:
- `board: tuple[tuple[int, ...], ...]`
- `current_seat: int`

Optional but acceptable if judged necessary for efficiency and clarity:
- none beyond the above in the initial design

Avoid storing these in v1 unless profiling later proves useful:
- winner
- is_terminal
- legal actions cache
- move count

These can be derived.

Board conventions should be explicitly documented:
- what numeric cell values mean
- row and column orientation
- whether row 0 is top or bottom

The most practical convention is:
- `0` = empty
- `1` = seat 0 disc
- `2` = seat 1 disc
- row 0 is the top row
- columns increase left to right

This keeps gravity logic straightforward.

## 9.4 Connect 4 action model

Use a single action type:

```python
@dataclass(frozen=True)
class DropDisc:
    column: int
```

No seat is embedded in the action.

## 9.5 Connect 4 observation model

Version 1 observation may mirror public state.

Recommended fields:
- `board`
- `current_seat`
- `legal_actions`

It is acceptable for observation serialization to expose derived human/API-friendly representations even if the in-memory state remains minimal.

## 9.6 Connect 4 result model

Rule results should support at least:
- seat win
- draw

Recommendation:
- generic shared result types in `arena.core.results`
- game-specific aliases only if needed

## 9.7 Connect 4 events

Recommended event set:
- `DiscDropped(seat, column, row)`
- `WinnerDetected(winning_seat)`
- `GameDrawn()`

These events should be emitted as part of the transition result.

## 9.8 Connect 4 rules behavior

### 9.8.1 Initial state

- empty board
- seat 0 to play first

### 9.8.2 Legal actions

Legal actions are all columns whose top cell is empty.

The return type should be a tuple of `DropDisc` actions ordered left to right.

### 9.8.3 Validation

Validation should check:
- the game is not already finished
- the acting seat equals `current_seat`
- the action type matches the game
- the column is within bounds
- the target column is not full

### 9.8.4 Apply action

Applying an action should:
- validate the action defensively
- find the lowest empty row in the chosen column
- place the correct disc value
- create a new immutable board
- derive whether the move created a winning line
- derive whether the board is now full without a winner
- switch the current seat only if the game continues
- emit domain events
- return the new state plus any result

### 9.8.5 Win detection

Win detection should check only lines affected by the latest move, not rescan the whole board unnecessarily.

Recommended directions:
- vertical
- horizontal
- diagonal descending
- diagonal ascending

A small helper for contiguous count by direction pair is recommended.

### 9.8.6 Terminal state

Terminal status should be derivable from the state and last transition context, or recomputed from board content when needed. The implementation should remain correct even if the library later reloads from a snapshot without the surrounding execution context.

This requirement implies that terminal/result derivation must not depend on hidden transient runtime state.

## 10. Serialization design

## 10.1 Goals

Serialization exists for:
- snapshots
- replay
- future transport adapters
- schema generation
- deterministic test fixtures

## 10.2 Boundary payloads

Boundary payloads should be Pydantic-backed and JSON-friendly.

Recommended principle:
- internal dataclasses remain the source of truth
- Pydantic payload models are explicitly constructed from internal objects

## 10.3 Required serializer operations

Each concrete game serializer should support:
- `dump_config(...)`
- `load_config(...)`
- `dump_state(...)`
- `load_state(...)`
- `dump_action(...)`
- `load_action(...)`
- `dump_observation(...)`
- `json_schema_*()` for boundary-facing models where useful

## 10.4 Snapshot payload content

Every state snapshot should include enough information to rehydrate the exact in-memory state.

Recommended payload metadata:
- game id
- schema version
- state payload

For example:

```json
{
  "game_id": "connect4",
  "schema_version": 1,
  "state": {
    "board": [[0,0,0,0,0,0,0], ...],
    "current_seat": 0
  }
}
```

The exact shape can vary, but the payload must be self-describing enough to support reliable rehydration.

## 10.5 Rehydration guarantees

Rehydration should guarantee:
- invalid payloads fail loudly
- shape mismatches are reported clearly
- loaded objects are real domain objects, not ad-hoc dicts

## 11. Generic test contract

Every game implementation must pass a shared generic contract suite.

## 11.1 Contract scope

The contract suite should verify at least:
- the game definition is registerable and discoverable
- initial state is valid
- current seat is valid
- legal actions are well-typed and non-empty when the game is ongoing
- each legal action validates successfully
- illegal actions fail predictably
- applying a legal action returns a new state and any appropriate events
- serialization round-trip preserves semantics
- rehydrated states behave the same as original states
- terminal states report results consistently

## 11.2 Contract extension points

A small fixture/factory layer should let each concrete game supply:
- a `GameDefinition`
- a valid config
- sample invalid configs
- at least one known near-terminal state
- at least one known terminal state

This allows the same generic test suite to run against future games.

## 12. Detailed implementation sequence

The implementation should proceed in small, verifiable slices.

## Phase 0 — Repository bootstrap

### Objective

Create the repository skeleton and baseline tooling without implementing game logic yet.

### Deliverables

- `pyproject.toml`
- package layout under `src/`
- test layout
- `AGENTS.md`
- `IMPLEMENTATION_PLAN.md`
- minimal `README.md`
- formatting and linting configuration
- test runner configuration

### Recommended tooling

Keep tooling modest. A reasonable baseline is:
- `pytest`
- `ruff`
- optionally `mypy`
- `pydantic>=2`

### Acceptance criteria

- editable install works in the virtual environment
- test discovery works
- lint command runs
- package imports cleanly

## Phase 1 — Core exception, type, and event foundations

### Objective

Establish the lowest-level shared domain primitives.

### Scope

Implement:
- base exception hierarchy
- seat aliases / helpers
- base domain event abstraction
- base result abstraction if needed early

### Acceptance criteria

- exceptions are importable and documented
- domain events are typed and immutable
- no game-specific logic leaks into this layer

## Phase 2 — Base config and serializer interfaces

### Objective

Define the shared contracts for validated config and serialization.

### Scope

Implement:
- base Pydantic config model with strict settings and forbidden extras
- serializer protocol / abstract base
- snapshot envelope model with schema version support

### Acceptance criteria

- config rejects unknown fields
- serializer contracts are stable and documented
- schema-generation path is demonstrable with a trivial model

## Phase 3 — Base game abstractions

### Objective

Define the reusable game-facing contracts.

### Scope

Implement:
- base action abstraction
- base observation abstraction
- `TransitionResult`
- `GameDefinition`
- `RulesEngine` interface
- `GameRegistry`

### Acceptance criteria

- a fake test game can be registered
- duplicate registration fails cleanly
- all public interfaces are typed and documented

## Phase 4 — Shared test contract harness

### Objective

Create the generic validation framework that all games must satisfy.

### Scope

Implement:
- generic contract test helpers
- factory/fixture conventions for game implementations
- first placeholder tests against a trivial stub game if useful

### Acceptance criteria

- contract harness can be reused by multiple games
- failure messages are understandable
- Connect 4 can plug into the harness later without redesign

## Phase 5 — Connect 4 config, state, actions, results, and events

### Objective

Implement the static domain model for the first real game.

### Scope

Implement:
- `Connect4Config`
- `Connect4State`
- `DropDisc`
- Connect 4 event classes
- any result aliases or game-specific wrappers if needed

### Acceptance criteria

- config validates correctly
- board representation is immutable and documented
- state objects are minimal and pure
- action and event models are explicit and typed

## Phase 6 — Connect 4 rules engine

### Objective

Implement all rule logic for Connect 4.

### Scope

Implement:
- `initial_state`
- `current_seat`
- `legal_actions`
- `validate_action`
- `apply_action`
- terminal/result derivation
- observation building
- win detection helpers

### Acceptance criteria

- legal moves are correct across empty, mid-game, and near-full boards
- illegal moves raise the expected domain exceptions
- wins are detected in all four relevant directions
- draws are detected correctly
- emitted events match the applied transition

## Phase 7 — Connect 4 serializer and snapshot rehydration

### Objective

Implement full serialization and round-trip support for the first game.

### Scope

Implement:
- config serialization / deserialization
- state snapshot serialization / rehydration
- action serialization / deserialization
- observation serialization
- JSON Schema generation for boundary-facing models

### Acceptance criteria

- round-trip tests pass
- malformed payloads fail clearly
- rehydrated state behaves identically to original state

## Phase 8 — Connect 4 definition and manual registration

### Objective

Make Connect 4 discoverable through the shared registry.

### Scope

Implement:
- `Connect4GameDefinition`
- registration helper
- default registry population path if desired

### Acceptance criteria

- registry resolves Connect 4 by stable id
- rule and serializer wiring is correct
- duplicate registration protections still hold

## Phase 9 — Contract tests against Connect 4

### Objective

Run the generic contract suite against a real game implementation.

### Scope

Implement:
- Connect 4 fixture adapters for the contract suite
- positive and negative unit tests where contract tests are not enough

### Acceptance criteria

- generic contract suite passes
- game-specific unit suite passes
- regression coverage exists for common edge cases

## Phase 10 — Documentation and example usage

### Objective

Document how the library is intended to be consumed.

### Scope

Provide:
- example code to create a game from the registry
- example code to get initial state
- example code to list legal actions
- example code to apply a move
- example code to serialize and rehydrate a state

### Acceptance criteria

- examples run or are test-backed
- examples do not expose internals that should remain private

## 13. Testing strategy in detail

## 13.1 Unit tests

Use unit tests for:
- validation helpers
- state transition helpers
- direction counting logic
- serializer round-trips
- registry behavior
- exception payloads

## 13.2 Contract tests

Use contract tests to guarantee all game implementations conform to the core interfaces and behaviors.

## 13.3 Regression tests

Add regression tests whenever a bug is found in:
- win detection
- draw detection
- immutable board reconstruction
- serializer round-trips
- event emission order

## 13.4 Suggested edge-case coverage for Connect 4

At minimum include:
- first move in each column
- full-column rejection
- horizontal win on left and right edges
- vertical win with stacked discs
- both diagonal win directions
- draw on full board without win
- validation of wrong acting seat
- apply action after terminal state
- snapshot round-trip of a mid-game state
- snapshot round-trip of a terminal state

## 14. Documentation strategy

The project should maintain separate forms of documentation.

### 14.1 `AGENTS.md`

Short repository context for coding agents.

### 14.2 `IMPLEMENTATION_PLAN.md`

Detailed technical roadmap and source of truth for sequencing.

### 14.3 `README.md`

Human-facing quick introduction and setup notes.

### 14.4 Docstrings

Public interfaces and non-obvious logic should be documented in code.

## 15. Versioning considerations

Even in v1, boundary payloads should anticipate future change.

Recommended minimum:
- stable `game_id`
- integer `schema_version` in serialized payloads

This is useful even before network APIs exist.

## 16. Deferred concerns

The following topics are intentionally deferred.

### 16.1 Arena orchestration

Deferred topics:
- match ids
- state versioning
- stale move detection
- timeout outcomes
- disconnect handling
- resignations
- tournament management

### 16.2 Network and UI adapters

Deferred topics:
- FastAPI routes
- WebSocket event streams
- frontend render models
- spectator dashboards

### 16.3 Storage technology

Snapshot persistence format is defined conceptually in this phase, but the actual database choice is deferred until the arena layer exists.

For the pure simulation package, it is sufficient to ensure snapshots are JSON-friendly and rehydratable.

### 16.4 Generalization to other game classes

Deferred topics:
- hidden information
- stochastic transitions
- simultaneous turns
- multiple phases and stages
- more than two players

The architecture should not block these, but they are not to be implemented in the first phase.

## 17. Risks and mitigation

### 17.1 Risk: over-engineering too early

Mitigation:
- keep the scope on pure simulation only
- resist building adapter and orchestration layers now
- add abstractions only where they already serve Connect 4 and future reuse clearly

### 17.2 Risk: leaking JSON and transport concerns into the core

Mitigation:
- keep internal state/action/event objects typed and Python-native
- confine serialization logic to serializer modules

### 17.3 Risk: brittle or under-specified contracts

Mitigation:
- implement the shared contract test suite early
- avoid vague interfaces that only one game can satisfy accidentally

### 17.4 Risk: non-rehydratable snapshots

Mitigation:
- treat serializer round-trip behavior as a first-class acceptance criterion
- test both ongoing and terminal states

### 17.5 Risk: inefficient or incorrect win detection

Mitigation:
- constrain win detection to last-move-based directional checks
- back the logic with exhaustive edge-case tests

## 18. Definition of done for the first milestone

The first milestone is complete when all of the following are true:
- the repository is bootstrapped and testable
- core abstractions are implemented and documented
- manual registry exists and works
- Connect 4 is fully implemented under the shared abstractions
- legal action generation and validation are correct
- pure state transitions are implemented defensively
- domain events are emitted for Connect 4 transitions
- snapshots and configs serialize and rehydrate correctly
- JSON Schema generation is available for boundary-facing models
- Connect 4 passes the shared generic contract suite
- game-specific regression tests exist for key edge cases

## 19. Suggested iteration policy

A productive implementation cycle for the coding agent is:
- select one phase or sub-phase
- break it into concrete tasks
- implement only that slice
- add tests immediately
- run the smallest relevant verification commands
- update this document with status notes if the plan changes materially

The plan should evolve only when there is a concrete architectural reason, not because of incidental implementation drift.
