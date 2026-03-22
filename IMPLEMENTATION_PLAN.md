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

### Phase 3 status

- completed

Corrective note:
- tightened the completed Phase 3 contracts by removing derived terminal logic from `TransitionResult`, making `GameDefinition.result_type` explicit, and extending registry coverage to reject duplicate `game_id` values across distinct definitions

Implementation note:
- applied one bounded corrective pass after review: `TransitionResult` was tightened back to a pure carrier without derived terminal logic, `GameDefinition.result_type` was made explicit instead of defaulting to the broad base result type, and registry coverage now locks duplicate `game_id` handling across distinct definitions

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

### Ordered slices


#### Slice 1 - Exception foundation `[done]`

Objective:
- freeze the shared exception hierarchy and payload contract for the simulation core

Scope:
- `arena.core.exceptions`
- focused exception tests

Status:
- completed

#### Slice 2 - Seat aliases and validation `[done]`

Objective:
- establish `Seat` as the canonical internal seat alias and add one narrow, non-coercing validation helper

Scope:
- `arena.core.types`
- `arena.core.seats`
- focused tests for seat alias and validation behavior

Constraints to preserve:
- keep `Seat = int`
- keep seat helpers narrowly about seat validity only
- reject `bool` explicitly even though it is an `int` subclass
- do not introduce seat-specific exceptions yet
- do not expand into player identity, labels, assignment, or turn logic

Acceptance criteria:
- `Seat` is defined as the canonical internal seat alias
- seat helpers remain minimal, explicit, and game-agnostic
- seat validation behavior is documented by tests
- valid non-negative integer seats are accepted without coercion
- invalid seat inputs such as `bool`, negative integers, floats, strings, and `None` are rejected predictably

Status:
- completed

Implementation note:
- implemented as `Seat = int` plus one narrow, non-coercing predicate helper; `arena.core` re-exports were intentionally left unchanged to avoid expanding the public API surface early

#### Slice 3 - Domain event foundation `[done]`

Objective:
- define the shared immutable event abstraction after seat identity is frozen

Scope:
- `arena.core.events`
- focused event tests

Acceptance criteria:
- the base domain event abstraction is importable and documented
- event objects are frozen, typed, and value-comparable
- the base event contract remains pure and game-agnostic
- subclasses can add typed event fields without requiring transport-oriented payload structures

Status:
- completed

Implementation note:
- implemented as a minimal frozen `DomainEvent` base with a derived `event_type` property so future game events can add strongly typed fields without inheriting transport-oriented payload requirements

#### Slice 4 - Base result abstraction if needed `[done]`

Objective:
- add a minimal shared result abstraction only if a concrete dependency appears before Phase 3

Scope:
- `arena.core.results` only if required
- focused result tests only if the slice is activated

Acceptance criteria:
- the shared result abstraction is importable and documented
- result objects are frozen, typed, and game-agnostic
- shared result types support at least generic win and draw outcomes without leaking Connect 4 specifics

Status:
- completed

Implementation note:
- activated this slice and implemented a minimal frozen `RuleResult` base plus generic `Win` and `Draw` value objects, keeping the contract game-agnostic and detached from Connect 4 specifics

### Phase 1 status

- completed

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

### Ordered slices

#### Slice 1 - Base config model `[done]`

Objective:
- freeze the shared Pydantic config behavior before serializer interfaces depend on it

Scope:
- `arena.core.config`
- focused config validation and schema tests

Acceptance criteria:
- the base config model is importable and documented
- unknown fields are rejected
- strict validation avoids unwanted coercion for trivial subclasses
- a trivial subclass can generate JSON Schema successfully

Status:
- completed

Implementation note:
- implemented as a minimal `BaseGameConfig` Pydantic base with `extra="forbid"` and `strict=True`, leaving game-specific defaults and extra metadata out of the shared contract

#### Slice 2 - Serializer contract `[done]`

Objective:
- define the shared serializer interface for config, state, action, and observation boundaries

Scope:
- `arena.core.serializer`
- focused serializer contract tests

Acceptance criteria:
- the serializer contract is importable and documented
- the contract clearly supports config, state, action, and observation dump/load operations
- the interface remains game-agnostic and free of Connect 4-specific assumptions
- a trivial implementation can satisfy the contract in tests

Status:
- completed

Implementation note:
- implemented as a runtime-checkable `Serializer` protocol plus shared JSON-safe payload type aliases, keeping the contract interface-only and deferring snapshot-envelope structure to the next slice

#### Slice 3 - Snapshot envelope `[done]`

Objective:
- define a stable, JSON-friendly snapshot envelope with schema version support

Scope:
- snapshot envelope model(s) in `arena.core.serializer`
- focused snapshot envelope tests

Acceptance criteria:
- the snapshot envelope is importable and documented
- it includes schema version support and stable metadata fields
- it is JSON-friendly and round-trips cleanly with a trivial payload
- malformed or incomplete envelope payloads fail clearly

Status:
- completed

Implementation note:
- implemented `SnapshotEnvelope` as a strict Pydantic boundary model with stable metadata plus serialized state, and switched the shared JSON payload alias to Pydantic's named recursive `JsonValue` for reliable envelope validation

### Phase 2 status

- completed

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

### Ordered slices

#### Slice 1 - Action, observation, and transition primitives `[done]`

Objective:
- introduce the shared action and observation abstractions plus the reusable transition result container

Acceptance criteria:
- base action and observation abstractions are explicit, typed, and game-agnostic
- `TransitionResult` captures the post-action state, emitted events, and optional terminal result
- focused tests cover importability, immutability, and core field semantics

Status:
- completed

Implementation note:
- introduced minimal frozen `Action` and `Observation` bases with stable type identifiers, and added a generic immutable `TransitionResult` container that normalizes emitted events to a tuple for predictable downstream handling

#### Slice 2 - Rules engine and game definition contracts `[done]`

Objective:
- define the reusable rules-engine and game-definition interfaces that concrete games will implement

Acceptance criteria:
- rules-engine and game-definition contracts are fully typed and documented
- contracts compose cleanly with the existing config, serializer, event, and result abstractions
- focused tests cover the expected interface surface with a trivial fake game

Status:
- completed

Implementation note:
- implemented `RulesEngine` as a runtime-checkable protocol and `GameDefinition` as a registry-facing wiring object so later phases can compose concrete games without coupling the simulation core to orchestration concerns

#### Slice 3 - Manual registry implementation `[done]`

Objective:
- implement the shared game registry and validate registration and lookup behavior end to end

Acceptance criteria:
- a fake test game can be registered and resolved by stable id
- duplicate registration fails cleanly with the shared domain exception
- listing and lookup behavior are deterministic and covered by tests

Status:
- completed

Implementation note:
- added a minimal in-memory `GameRegistry` with deterministic insertion-order listing and shared duplicate and unknown-game errors, deferring any default-population helpers to the later registration phase

### Phase 3 status

- completed

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

### Ordered slices

#### Slice 1 - Testing package skeleton and fake-game factory conventions `[done]`

Objective:
- create the shared testing-layer package and freeze one minimal fake-game factory convention before writing reusable contract assertions

Scope:
- `arena.testing.__init__`
- `arena.testing.factories`
- focused unit tests for fake-game bundle construction and shared testing imports

Acceptance criteria:
- a minimal fake game stack exists in the testing layer with config, state, action, observation, rules engine, serializer, and `GameDefinition`
- the fake-game helpers stay game-agnostic and do not import Connect 4 symbols
- the fake bundle exposes coherent typed Python objects rather than JSON-first payloads
- the fake-game definition sets `result_type` explicitly and composes with the current core contracts

Status:
- completed

Implementation note:
- added an `arena.testing` package plus a minimal fake-game bundle with explicit `result_type`, near-terminal and terminal fixture states, predictable illegal-action coverage, and serializer round-trip checks so later contract assertions can stay game-agnostic

#### Slice 2 - Reusable contract assertion helpers `[done]`

Objective:
- implement the generic contract assertions as reusable helpers that validate only shared simulation guarantees

Scope:
- `arena.testing.contracts`
- focused unit tests for positive cases, negative cases, and readable assertion messages

Acceptance criteria:
- the harness checks valid initial state, legal action generation, illegal action rejection, state transition behavior, terminal/result consistency, and serializer round-trip / rehydration
- serializer checks go through the shared serializer contract instead of direct object equality alone
- helpers remain game-agnostic and rely only on shared core contracts and the fake-game factory convention
- failure messages identify which contract failed and why

Status:
- completed

Implementation note:
- added reusable contract assertions over the shared fake-game bundle, tightened legal-action type checking against `GameDefinition.action_type`, and switched serializer round-trip verification to compare public state semantics rather than relying on direct state equality alone

#### Slice 3 - Placeholder contract suite against the fake game `[done]`

Objective:
- prove the shared harness works end to end through a pytest-discoverable contract test module

Scope:
- `tests/contract/test_game_contract.py`
- any focused harness smoke tests needed to prove repeated execution remains deterministic

Acceptance criteria:
- a reusable contract test entry point exists and runs against the fake game without Connect 4-specific assumptions
- the contract suite is clearly separated from focused unit tests
- repeated runs against fresh fake-game fixtures are deterministic
- the harness can be reused by Connect 4 in Phase 9 without redesign

Status:
- completed

Implementation note:
- added a dedicated `tests/contract/` entry point that runs the shared contract suite against fresh fake-game bundles and locks deterministic repeated execution without introducing Connect 4-specific assumptions

### Phase 4 status

- completed

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

### Ordered slices

#### Slice 1 - Connect 4 package scaffold and config `[done]`

Objective:
- introduce the Connect 4 package boundary and freeze the validated config model before state and rules logic depend on it

Scope:
- `arena.games.connect4.__init__`
- `arena.games.connect4.config`
- focused package/import and config validation tests

Acceptance criteria:
- the Connect 4 package is importable without pulling in rule or serializer wiring from later phases
- `Connect4Config` inherits the shared config behavior and validates the supported board dimensions and connect length
- unknown fields and invalid numeric combinations fail clearly
- tests lock the accepted defaults and validation edge cases for later phases

Status:
- completed

Implementation note:
- added the initial `arena.games.connect4` package and kept `Connect4Config` limited to validated board-shape parameters so later state and rules slices can stay pure and derive runtime behavior from state alone

#### Slice 2 - Connect 4 state and action models `[done]`

Objective:
- introduce the immutable state and move domain objects with explicit board conventions and no derived runtime caches

Scope:
- `arena.games.connect4.state`
- `arena.games.connect4.actions`
- package exports needed for the static model surface
- focused state/action tests

Acceptance criteria:
- `Connect4State` is a frozen dataclass with only authoritative state fields
- the board representation is a tuple of tuples and its orientation and cell encoding are documented in code
- `DropDisc` is a frozen seat-agnostic action type with explicit column data only
- tests cover importability, immutability, equality semantics, and representative board construction

Status:
- completed

Implementation note:
- kept `Connect4State` limited to `board` plus `current_seat`, added lightweight invariants for rectangular boards and valid disc values, and exposed small board-value helpers that later rules logic can reuse without caching derived state

#### Slice 3 - Connect 4 events and result surface `[done]`

Objective:
- define the pure Connect 4 domain events and lock whether Phase 5 needs any game-specific result wrappers beyond the shared core results

Scope:
- `arena.games.connect4.events`
- `arena.games.connect4.__init__`
- focused event/result-surface tests

Acceptance criteria:
- Connect 4 exposes explicit typed events for disc drops, wins, and draws
- event payloads carry only simulation-domain data needed by later rule transitions
- any result surface decision remains compatible with the shared `Win` and `Draw` abstractions
- tests cover immutability, stable event typing, and public exports

Status:
- completed

Implementation note:
- kept Connect 4 on the shared `Win` and `Draw` result surface, added explicit public-export coverage for `DiscDropped`, `WinnerDetected`, and `GameDrawn`, and left event payload validation intentionally minimal so Phase 6 can emit events from validated rule transitions

### Phase 5 status

- completed

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

### Ordered slices

#### Slice 1 - Rules engine scaffold, initial state, and move validation `[done]`

Objective:
- implement the core rules-engine scaffold plus the non-terminal mechanics that define whose turn it is and which actions are legal

Scope:
- `arena.games.connect4.observation`
- `arena.games.connect4.rules`
- focused rules tests for initial state, current seat, legal actions, and validation failures

Acceptance criteria:
- `initial_state` builds an empty immutable board from `Connect4Config`
- `current_seat` returns the seat stored in state without hidden runtime context
- `legal_actions` returns left-to-right `DropDisc` actions only for playable columns and no actions for terminal states
- `validate_action` raises the expected domain exceptions for finished games, wrong seats, wrong action types, out-of-bounds columns, and full columns

Status:
- completed

Implementation note:
- introduced a minimal `Connect4RulesEngine` plus typed `Connect4Observation`, locking initial-state creation, turn lookup, left-to-right legal action generation, and defensive validation now while intentionally deferring move application and win detection to the next slice

#### Slice 2 - Apply-action transitions, win detection, and terminal results `[done]`

Objective:
- implement pure state transitions, last-move win detection, and terminal result derivation for Connect 4

Scope:
- `arena.games.connect4.rules`
- focused transition tests for gravity placement, seat switching, win detection, draw detection, and emitted event order

Acceptance criteria:
- `apply_action` validates defensively, places a disc in the lowest available row, and returns a new immutable state
- win detection covers vertical, horizontal, and both diagonal directions based on the latest move
- terminal states produce the expected shared result objects and stop turn switching
- emitted events match the applied transition for ongoing, winning, and drawn moves

Status:
- completed

Implementation note:
- implemented immutable drop transitions with ordered domain events, covered all four win directions plus draw detection, and bound the active `Connect4Config` to the rules engine so non-default `connect_length` values remain coherent without expanding `Connect4State`

#### Slice 3 - Observation building and rules regression coverage `[done]`

Objective:
- complete the player-facing observation path and lock the Connect 4 rules behavior with focused regression tests around edge cases

Scope:
- `arena.games.connect4.observation`
- `arena.games.connect4.rules`
- focused observation and regression tests for near-full boards, terminal observations, and repeated legality checks

Acceptance criteria:
- `observation` returns a typed Connect 4 observation with public board state, active seat, and structured legal actions
- observations stay deterministic and coherent with `legal_actions` for the requested seat
- focused regression tests cover edge cases called out in the implementation plan for Phase 6 scope
- the rules module exports remain stable for later serializer, definition, and contract-suite work

Status:
- completed

Implementation note:
- tightened the public observation type to use the shared `Seat` alias, added regression coverage for non-active-seat views, terminal and near-full observations, repeated-call stability, and locked `Connect4Observation` / `Connect4RulesEngine` package exports for later phases

### Phase 6 status

- completed

Verification note:
- final full-suite verification exposed pytest import-name collisions between core and Connect 4 test modules, so the `tests/` tree was turned into explicit packages with `__init__.py` files as the smallest corrective change needed to keep repository-wide test collection stable

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

### Ordered slices

#### Slice 1 - Connect 4 serializer happy-path payloads `[done]`

Objective:
- introduce the concrete Connect 4 serializer boundary and lock the stable payload shape for config, action, and observation round-trips

Scope:
- `arena.games.connect4.serializer`
- `arena.games.connect4.__init__`
- focused serializer tests for config, action, and observation round-trips

Acceptance criteria:
- `Connect4Serializer` implements the shared serializer contract for config, action, and observation payloads
- serialized config, action, and observation payloads are JSON-friendly and round-trip to the original typed objects
- the payload shape stays explicit and boundary-facing without leaking serializer concerns into the rules engine
- the public Connect 4 package surface exports the serializer type if Phase 7 introduces it

Status:
- completed

Implementation note:
- introduced a dedicated `arena.games.connect4.serializer` module with strict Pydantic payload models for config, action, and observation boundaries, exported `Connect4Serializer` from the package surface, and intentionally left state snapshot methods as explicit `NotImplementedError` placeholders to keep the slice bounded for follow-up work

#### Slice 2 - State snapshot dump/load and behavioral rehydration `[done]`

Objective:
- add state snapshot serialization and rehydration that preserves Connect 4 gameplay semantics across fresh and reused rules-engine instances

Scope:
- `arena.games.connect4.serializer`
- focused serializer and regression tests for initial, mid-game, and terminal state snapshots

Acceptance criteria:
- `dump_state` and `load_state` round-trip initial, mid-game, and terminal `Connect4State` values
- rehydrated states preserve tuple-based board structure, active seat, terminal status, result, legal actions, and observations
- snapshot payloads remain compatible with the shared `SnapshotEnvelope`
- regression coverage proves rehydrated state behavior does not depend on hidden runtime context beyond the authoritative snapshot data

Status:
- completed

Implementation note:
- implemented `Connect4State` dump/load via a dedicated snapshot payload model, expanded the shared `SnapshotEnvelope` to carry serialized config alongside state as the smallest corrective change needed for behavior-preserving rehydration, and added regression checks that rebuild Connect 4 semantics from snapshot data on both fresh and reused rules-engine setup paths

#### Slice 3 - Strict malformed payload rejection `[done]`

Objective:
- make Connect 4 boundary payload validation fail clearly and deterministically for malformed config, state, action, and observation inputs

Scope:
- `arena.games.connect4.serializer`
- focused negative serializer tests

Acceptance criteria:
- missing required fields, wrong primitive types, and unexpected extra fields fail clearly across all Connect 4 loader entry points
- invalid board payload shapes, invalid disc values, and invalid seats are rejected during state rehydration
- malformed payloads are rejected by strict boundary validation instead of silent coercion
- negative tests lock the expected failure surface without broadening shared core contracts unnecessarily

Status:
- completed

Implementation note:
- tightened the Connect 4 serializer boundary with strict seat constraints plus shared board-shape and disc-value validation for state and observation payloads, then locked the negative surface with focused malformed-payload tests across config, action, state, and observation loaders

#### Slice 4 - JSON Schema coverage and serializer surface stabilization `[done]`

Objective:
- expose JSON Schema generation for Connect 4 boundary-facing serializer models and lock the serializer module surface for later definition and contract work

Scope:
- `arena.games.connect4.serializer`
- `arena.games.connect4.__init__`
- focused schema and export tests

Acceptance criteria:
- boundary-facing Connect 4 serializer models can emit JSON Schema successfully
- schema assertions cover expected required fields and core primitive shapes for config, state snapshot, action, and observation payloads
- serializer exports remain stable for later `GameDefinition` wiring
- the completed Phase 7 test suite demonstrates round-trips, strict failures, and schema generation coherently

Status:
- completed

Implementation note:
- added JSON Schema assertions for the shared snapshot envelope and the Connect 4 config, action, state, and observation payload models, keeping schema generation anchored at the serializer boundary while confirming the package-level serializer export remains stable for later definition wiring

### Phase 7 status

- completed

Verification note:
- Phase 7 final verification passed with `.\\.venv\\Scripts\\python.exe -m pytest -q` covering the full repository, including the new Connect 4 serializer, snapshot, malformed-payload, and schema checks

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
