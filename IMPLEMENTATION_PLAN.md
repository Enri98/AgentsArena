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

### Ordered slices

#### Slice 1 - Connect 4 definition wiring `[done]`

Objective:
- add the registry-facing Connect 4 definition that binds the concrete config, state, action, observation, rules, serializer, and shared result surface

Scope:
- `arena.games.connect4.definition`
- `arena.games.connect4.__init__`
- focused definition wiring tests

Acceptance criteria:
- a stable Connect 4 game id is exposed for registry lookup
- the definition wires `Connect4Config`, `Connect4State`, `DropDisc`, `Connect4Observation`, `Connect4RulesEngine`, `Connect4Serializer`, and the shared `RuleResult` surface coherently
- the public Connect 4 package surface exports the definition entry point

Status:
- completed

Implementation note:
- introduced a dedicated registry-facing definition module with a stable `connect4` id and exported the resolved definition from the package surface so the registry can resolve the game without adding any transport or orchestration concerns

#### Slice 2 - Manual registration helper and registry coverage `[done]`

Objective:
- add a small helper that registers Connect 4 into a supplied registry and lock duplicate registration behavior with focused tests

Scope:
- `arena.games.connect4.definition`
- focused registry-resolution tests

Acceptance criteria:
- a registration helper adds Connect 4 to a `GameRegistry`
- duplicate registration still raises the shared duplicate-registration error
- tests prove registry lookup, initial-state creation, legal-action exposure, and serializer round-trip behavior through the resolved definition

Status:
- completed

Implementation note:
- kept registration as a thin helper around the shared `GameRegistry`, reused the single Connect 4 definition instance for registry discovery, and verified the resolved definition still drives the rules engine and serializer correctly from the registry boundary

#### Slice 3 - Built-in registry convenience helpers `[done]`

Objective:
- expose a small public helper for registering built-in games and a default-registry constructor for callers that do not want to wire each game manually

Scope:
- `arena.games.__init__`
- README quickstart
- focused registry-helper tests

Acceptance criteria:
- `register_builtin_games(registry)` registers the built-in games into an existing registry
- `build_default_registry()` returns a fresh registry with the built-in games already registered
- duplicate registration behavior continues to come from `GameRegistry`

Status:
- completed

Implementation note:
- added package-level convenience wrappers around the existing Connect 4 registration helper so the registry stays generic while callers get a one-line built-in registry path

### Phase 8 status

- completed

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

### Ordered slices

#### Slice 1 - Registry-facing Connect 4 contract bundle `[done]`

Objective:
- adapt the shared contract-suite fixture shape to the real Connect 4 implementation using the registry-facing definition from Phase 8

Scope:
- `tests/contract/test_connect4_contract.py`
- shared contract-bundle fixture assembly

Acceptance criteria:
- the bundle uses `Connect4GameDefinition` directly rather than reconstructing an alternate definition
- the bundle supplies a legal action that works from both the initial state and the near-terminal state
- the bundle supplies a terminal state that exactly matches the rules-engine transition from the near-terminal state
- the bundle supplies an illegal action that is rejected from the initial state

Status:
- completed

Implementation note:
- built a test-local Connect 4 contract bundle around the registry-facing `Connect4GameDefinition`, using `DropDisc(column=0)` as the shared legal action and `DropDisc(column=config.columns)` as the deliberately illegal action so the shared contract can exercise the real rules engine without adding production-only adapter code

#### Slice 2 - Shared contract-suite coverage and fixture regressions `[done]`

Objective:
- run the reusable generic contract suite against the real Connect 4 implementation and lock the near-terminal / illegal-action fixtures with focused regression checks

Scope:
- `tests/contract/test_connect4_contract.py`

Acceptance criteria:
- `assert_game_contract` passes for real Connect 4
- the near-terminal fixture reaches the expected winning terminal state
- the illegal-action fixture is rejected from the initial state

Status:
- completed

Implementation note:
- added contract coverage that executes the shared assertion bundle against the real Connect 4 definition and pinned the fixture-specific win and rejection cases with narrow unit checks so the generic suite remains the main source of behavioral coverage

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

### Ordered slices

#### Slice 1 - README quickstart and scope rewrite `[done]`

Objective:
- replace the bootstrap placeholder README with a concise human-facing quickstart for the simulation package

Scope:
- `README.md`

Acceptance criteria:
- the README states the current simulation-only scope clearly
- the README shows the intended usage path through registry, rules engine, and serializer
- the README examples use public Connect 4 entry points rather than private internals

Status:
- completed

Implementation note:
- rewrote the README as a short quickstart centered on `GameRegistry`, `register_connect4(...)`, `definition.rules_engine`, and `definition.serializer`, with one compact Connect 4 example that covers registration, state creation, legal actions, move application, and config/state round-tripping

#### Slice 2 - Test-backed README example coverage `[done]`

Objective:
- add a focused regression test that exercises the README quickstart flow through the real public API

Scope:
- `tests/unit/docs/test_readme_quickstart.py`

Acceptance criteria:
- the example flow is covered by a test that registers Connect 4, creates initial state, lists legal actions, applies a move, and round-trips state and config serialization
- the coverage remains small and stable without relying on brittle markdown parsing

Status:
- completed

Implementation note:
- added a narrow end-to-end example test that follows the README path exactly through the registry-facing Connect 4 surface and verifies the serialized payloads rehydrate to the original typed objects

### Phase 10 status

- completed

Baseline hardening note:
- repository-wide Ruff cleanup was completed without behavior changes; this slice only touched import ordering, line wrapping, and plan status bookkeeping

Verification note:
- the example flow is now anchored by a unit test, and the repository-wide test suite will be run after the doc and test updates to confirm nothing drifted

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

### First milestone status

- completed

Verification note:
- the Connect 4 simulation baseline now has registry discovery, rules, events, serialization, schema coverage, shared contract coverage, README-backed usage examples, and clean repository-wide `pytest` / `ruff` verification

## 19. Suggested iteration policy

A productive implementation cycle for the coding agent is:
- select one phase or sub-phase
- break it into concrete tasks
- implement only that slice
- add tests immediately
- run the smallest relevant verification commands
- update this document with status notes if the plan changes materially

The plan should evolve only when there is a concrete architectural reason, not because of incidental implementation drift.

## 20. Post-baseline roadmap

The Connect 4 simulation baseline is complete. The next phase should move toward an arena product without contaminating the pure simulation layer.

The guiding boundary for this roadmap is:
- `arena.core` and `arena.games` remain pure simulation code
- local match execution belongs in a separate package area
- networking, persistence, deadlines, auth, and real agent connectivity remain deferred until a pure local runner is stable

### Phase 11 - Pure local match execution

Objective:
- provide a deterministic local runner that executes a game definition with submitted actions and records the authoritative transition history

Scope:
- local match/session models outside `arena.core` and `arena.games`
- runner initialization from a `GameDefinition` and config
- action submission through `rules_engine.apply_action(...)`
- serialized pre/post snapshots through the game serializer
- emitted domain events and terminal result capture

Out of scope:
- agent processes
- matchmaking
- state-version conflict handling
- clocks, timeouts, deadlines
- persistence
- web APIs or UI payloads

Acceptance criteria:
- a match can be started from a registered game definition
- each accepted action produces an immutable turn record containing seat, action, events, result, and a full post-move serialized snapshot
- the initial state is recorded as a serialized snapshot
- illegal actions continue to raise the underlying simulation-layer domain exceptions
- terminal games reject further actions through the rules engine
- tests cover a complete Connect 4 local match flow

#### Slice 1 - Local match session execution `[done]`

Objective:
- add a pure local match package that stores typed state alongside serialized snapshots and appends immutable turn records for each accepted move

Scope:
- `arena.match`
- focused unit tests for match initialization, transition recording, winning flow, and domain-exception propagation

Acceptance criteria:
- a match can be started from a `GameDefinition` and config
- the initial match state stores the typed current game state and a serialized initial snapshot envelope
- each accepted action appends an immutable turn record with seat, action, events, result, post-state, and post-move snapshot
- illegal and post-terminal actions surface the underlying simulation-layer domain exceptions

Status:
- completed

Implementation note:
- added a frozen `arena.match` package with `LocalMatch` and `TurnRecord` dataclasses plus pure `start_match(...)` / `apply_match_action(...)` helpers that delegate legality and terminal checks to the game definition's rules engine and use the existing serializer for snapshot envelopes

#### Slice 2 - Per-match rules-engine isolation `[done]`

Objective:
- ensure each local match owns its own rules engine instance so game-specific config state cannot leak across concurrently running matches

Scope:
- `arena.match`
- focused regression coverage for multiple Connect 4 matches started from the same definition with different configs

Acceptance criteria:
- a local match stores a per-match rules engine copy instead of reusing the shared definition singleton
- one match's config does not affect another match started from the same definition
- the match layer still preserves `match.definition` for metadata and serializer access

Status:
- completed

Implementation note:
- copied the game definition's rules engine when starting a local match, stored that isolated engine on `LocalMatch`, and added a regression that starts two Connect 4 matches from the same singleton definition with different configs to prove they no longer interfere

#### Slice 3 - README-backed local match usage `[done]`

Objective:
- document the public local match helpers in the README and cover the example with a focused docs test

Scope:
- `README.md`
- `tests/unit/docs/test_readme_quickstart.py`

Acceptance criteria:
- the README shows a concise local match flow using `build_default_registry()`, `Connect4Config`, `DropDisc`, `start_match(...)`, and `apply_match_action(...)`
- the README example is backed by a unit test that exercises the same public API path

Status:
- completed

Implementation note:
- added a compact local match example immediately after the existing simulation quickstart and anchored it with a matching docs test that verifies the immutable turn history and serialized post-move snapshot

### Phase 12 - Rehydratable match transcripts

Objective:
- make local match history exportable and rehydratable without adding storage infrastructure

Scope:
- transcript payload models
- JSON-safe dump/load of match records and snapshots
- deterministic replay validation against the game definition

Out of scope:
- databases
- event buses
- distributed replay feeds

Acceptance criteria:
- a completed local match transcript can be serialized to JSON-safe data
- rehydrating the transcript reconstructs the latest game state
- replay validation catches action/state mismatches

Status:
- Slice 1 completed
- Slice 2 completed

Implementation note:
- added JSON-safe transcript payload models and local match dump/load helpers under `arena.match`, then added deterministic replay validation that replays loaded actions against a fresh local match and checks snapshots, event payloads, and result metadata for mismatches

### Phase 13 - Minimal agent-facing local protocol

Objective:
- define the smallest local Python protocol needed for automated players to choose actions

Scope:
- typed protocol for an in-process player policy
- runner utility that asks the active policy for an action and applies it
- tests with deterministic fake policies

Out of scope:
- remote agents
- subprocess management
- network protocols
- LLM provider integration
- timeouts

Acceptance criteria:
- two in-process policies can complete a Connect 4 match through the local runner
- policy inputs use observations, not mutable internal state
- illegal policy actions surface as domain errors without being normalized into transport-specific failures

#### Slice 1 - In-process policy protocol and local auto-play `[done]`

Objective:
- add the smallest typed in-process policy protocol plus pure local helpers for applying one policy-selected turn or running a match to terminal

Scope:
- `arena.match`
- focused unit tests for observation-based policy selection, terminal auto-play, illegal-action propagation, and missing-policy failure

Acceptance criteria:
- the active seat's policy is selected from a seat-to-policy mapping
- policy input is built from the rules engine observation, not mutable state access
- a supplied seat-to-policy mapping can run a Connect 4 match to terminal
- illegal policy actions continue to raise the underlying domain exception
- missing active-seat policies fail clearly with a simple lookup error

Status:
- completed

Implementation note:
- added a local `Policy` protocol plus `apply_policy_turn(...)` and `run_local_match(...)` helpers under `arena.match`, then covered them with deterministic fake Connect 4 policies that assert observation delivery, full-match auto-play, domain-error propagation, and clear missing-seat lookup failures

### Phase 14 - Arena orchestration design checkpoint

Objective:
- decide whether to introduce real arena infrastructure or add another game first

Decision inputs:
- how reusable the local runner is after Connect 4
- whether a second game is needed to validate abstractions
- whether agent process boundaries are now worth designing

Potential next branches:
- add a second deterministic perfect-information game to stress the simulation contracts
- introduce process/network adapters around the local policy protocol
- introduce persistence for transcripts and snapshots

Checkpoint status:
- reached

Recommended next branch:
- add a second small deterministic perfect-information game before introducing remote/process infrastructure

Rationale:
- the pure simulation baseline, local match runner, transcript replay validation, and in-process policy protocol are now implemented against Connect 4 only
- a second game will reveal whether the shared contracts and match/transcript layers are actually reusable before adapter, process, or network concerns make changes more expensive
- remote agents, timeouts, storage, and APIs should remain deferred until the reusable local abstractions survive at least one more game implementation

### Phase 15 - Second deterministic perfect-information game

Objective:
- add Tic-Tac-Toe as a simpler second vertical slice to validate that the simulation core, registry, serialization, and contract suite generalize cleanly beyond Connect 4

Scope:
- `arena.games.tictactoe`
- built-in registry wiring
- focused unit tests for action, config, state, rules, events, serializer, and definition behavior
- shared contract coverage for the real Tic-Tac-Toe implementation
- registry helper coverage for the default built-in game set

Acceptance criteria:
- Tic-Tac-Toe is available through the built-in registry alongside Connect 4
- the shared contract suite passes for the real Tic-Tac-Toe implementation
- the Tic-Tac-Toe serializer round-trips config, state, action, and observation payloads
- legal actions are generated in row-major order and terminal state/result logic is consistent
- invalid payloads and illegal actions are rejected with domain-appropriate errors

#### Slice 1 - Full Tic-Tac-Toe vertical slice `[done]`

Objective:
- implement the full deterministic perfect-information Tic-Tac-Toe package as a compact second game slice

Status:
- completed

Implementation note:
- added a new `arena.games.tictactoe` package with frozen domain models, pure rules, strict serializers, registry wiring, shared-contract coverage, and focused unit tests, then wired the game into the built-in registry so the default game set now contains both Connect 4 and Tic-Tac-Toe

#### Slice 2 - Docs / integration / handoff completion `[done]`

Objective:
- close the remaining documentation and cross-layer coverage for the Tic-Tac-Toe slice

Scope:
- `README.md`
- `docs/NEXT_SESSION_PROMPT.md`
- `tests/unit/games/tictactoe/__init__.py`
- `tests/unit/match/test_tictactoe_integration.py`

Acceptance criteria:
- the README states that Connect 4 and Tic-Tac-Toe are built-in games
- default registry coverage proves Tic-Tac-Toe resolves through the public game registry
- local match helpers work end-to-end for Tic-Tac-Toe
- transcript dump and validation cover a completed Tic-Tac-Toe match
- a concise next-session prompt exists for handoff

Status:
- completed

Implementation note:
- added the package marker, a focused match integration test, a concise handoff prompt, and a small README scope update without changing the Tic-Tac-Toe rules implementation

### Phase 16 - README-backed local match examples

Objective:
- document the completed local transcript and in-process policy APIs before introducing any adapter, persistence, or orchestration boundary

Scope:
- `README.md`
- `tests/unit/docs/test_readme_quickstart.py`

Out of scope:
- remote agents
- process management
- network protocols
- persistence
- timeouts
- UI payloads

Acceptance criteria:
- the README shows transcript export and deterministic replay validation through `dump_match_transcript(...)` and `validate_match_transcript(...)`
- the README shows deterministic in-process policy auto-play through `run_local_match(...)`
- the examples are covered by focused docs tests using the public API
- `arena.core` and `arena.games` remain unchanged

#### Slice 1 - Transcript and policy docs examples `[done]`

Objective:
- add test-backed README examples for the already-implemented local transcript and policy helpers

Status:
- completed

Implementation note:
- expanded the local match README path to include JSON-safe transcript dumping and replay validation, added a deterministic observation-based policy example, and backed both examples with focused docs tests without changing runtime behavior

### Phase 17 - Adapter boundary design checkpoint

Objective:
- define adapter-layer guardrails before adding any process, network, persistence, or orchestration code

Decision inputs:
- Connect 4 and Tic-Tac-Toe now validate that the core game abstractions generalize across two deterministic perfect-information games
- local match execution, transcript validation, and observation-based in-process policies are stable enough to describe as adapter inputs
- adding infrastructure without a boundary document would risk leaking transport or orchestration concerns into `arena.core`, `arena.games`, or `arena.match`

Scope:
- `docs/ADAPTER_BOUNDARIES.md`
- `tests/unit/architecture/test_adapter_boundaries.py`
- `docs/NEXT_SESSION_PROMPT.md`
- `IMPLEMENTATION_PLAN.md`

Out of scope:
- adapter implementation packages
- server code
- process management
- remote agent protocols
- persistence
- deadlines and timeout outcomes
- matchmaking
- UI payloads

Acceptance criteria:
- the design document states the allowed dependency direction between future adapters and existing pure packages
- the design document identifies stable adapter inputs and outputs using existing serializers, observations, transcripts, and domain exceptions
- deferred infrastructure concerns remain explicitly out of scope
- architecture tests enforce that `arena.core`, `arena.games`, and `arena.match` do not import future adapter packages
- the next-session handoff points to the boundary checkpoint before implementation work

#### Slice 1 - Adapter boundary design document `[done]`

Objective:
- capture the future adapter seam without adding runtime adapter code

Status:
- completed

Implementation note:
- added `docs/ADAPTER_BOUNDARIES.md` to define dependency direction, allowed inputs/outputs, forbidden infrastructure concerns, and the first safe future adapter slice, then added import-boundary tests to keep existing pure packages independent from future adapters while leaving runtime packages unchanged

### Phase 18 - Pure in-process adapter payload contract

Objective:
- add the smallest adapter-facing payload contract for in-process action selection without introducing transport, persistence, process management, deadlines, or UI concerns

Scope:
- `arena.adapters`
- focused adapter unit tests
- architecture boundary tests remain in force
- documentation and handoff notes

Out of scope:
- FastAPI or WebSocket APIs
- remote agent protocols
- subprocess management
- persistent transcript storage
- stale-version handling
- clocks and timeout outcomes
- authentication and authorization
- matchmaking and tournaments
- UI render payloads

Acceptance criteria:
- adapter-facing observation requests are JSON-safe payloads built from `rules_engine.observation(...)` and game serializers
- adapter-facing action responses are rehydrated through the game serializer before being applied through the existing local match helper
- domain exceptions raised by rules engines remain unchanged and can be dumped to metadata-preserving boundary payloads
- adapter helpers do not add a second match runner or bypass `arena.match.apply_match_action(...)`
- `arena.core`, `arena.games`, and `arena.match` do not import adapter code

#### Slice 1 - Serialized in-process policy turn `[done]`

Objective:
- support one serialized in-process policy turn over the existing local match API

Status:
- completed

Implementation note:
- added `arena.adapters.in_process` with strict Pydantic payloads for observation requests, action responses, and domain errors; the helper builds observations via the active match rules engine, loads actions through the game serializer, and applies them through `apply_match_action(...)` with focused unit coverage for serialization, action loading, domain-error preservation, and response mismatch rejection

### Phase 19 - Typed in-process adapter convenience wrapper

Objective:
- make the serialized in-process adapter contract easier to use with typed local agents while keeping the payload boundary authoritative

Scope:
- `arena.adapters.in_process`
- focused adapter unit tests
- documentation and handoff notes

Out of scope:
- network protocols
- subprocess management
- persistence
- deadlines and timeout outcomes
- UI payloads
- a second match runner
- changes to `arena.core`, `arena.games`, or `arena.match`

Acceptance criteria:
- a typed in-process agent can receive a typed observation rehydrated from `ObservationRequestPayload`
- the typed agent's action is serialized into `ActionResponsePayload` through the game serializer
- the wrapper remains usable anywhere a `PayloadPolicy` is expected
- foreign game ids and schema-version mismatches are rejected before invoking the typed agent
- wrong action types continue to surface serializer/type errors instead of being normalized into adapter-specific errors

#### Slice 1 - Typed payload policy adapter `[done]`

Objective:
- adapt typed local agents to the existing payload policy contract without adding a new runner

Status:
- completed

Implementation note:
- added `InProcessAgent` and `TypedPayloadPolicyAdapter`, which validate payload metadata, load observations through the game serializer, call the typed agent, dump typed actions through the serializer, and then remain compatible with `apply_payload_policy_turn(...)`

### Phase 20 - Match / arena layer design checkpoint

Objective:
- decide what belongs in the match / arena layer before adding orchestration code

Decision inputs:
- the simulation layer is complete enough for the current deterministic perfect-information scope
- `arena.match` already provides immutable single-match execution and transcript validation
- `arena.adapters.in_process` provides a pure in-process adapter boundary without remote infrastructure
- the next layer must not leak transport, persistence, timeout, auth, matchmaking, or rendering concerns into simulation code

Decisions:
- name the next package `arena.runtime`
- introduce a small higher-level `Arena` object as the pure in-memory coordinator for local runtime sessions
- keep `LocalMatch` as the authoritative deterministic single-match execution primitive
- add opaque runtime match ids in the first runtime slice
- allow caller-provided match ids for reproducibility and expose a small default id generator for demos and convenience
- represent players with runtime-owned records containing `player_id`, optional `label`, and assigned integer `seat`
- keep player records separate from policy bindings so identity metadata is not coupled to in-process execution machinery
- use an explicit runtime lifecycle with `created`, `running`, `finished`, and `aborted`
- treat all non-game-result failures as runtime aborts while preserving the original exception as the cause where possible
- let `arena.core` remain the authority for rule validation; runtime may catch `ArenaCoreError` at the boundary and convert it into an aborted runtime outcome
- keep transcript validation explicit instead of running it automatically after every local run
- wrap existing `arena.match` transcript payloads with runtime/session metadata instead of extending `MatchTranscriptPayload`
- add runtime events distinct from game-domain events
- consider UI-facing payloads now, but keep them as stable data envelopes derived from runtime/session state rather than UI rendering logic

Runtime owns:
- match identity
- player and seat assignment records
- local runtime lifecycle state
- runtime abort reasons and error boundaries
- runtime event records
- ownership of session-level transcript envelopes
- adapter/policy binding for local in-process execution
- UI-ready session status and transcript payloads that do not contain presentation or rendering decisions

Runtime must not own yet:
- FastAPI or WebSocket APIs
- remote agents
- subprocess management
- persistence
- stale-version handling
- deadlines and timeout outcomes
- authentication and authorization
- matchmaking queues
- tournaments
- concrete UI rendering logic

#### Slice 1 - Runtime package boundary and architecture tests

Objective:
- create the `arena.runtime` package boundary without broad orchestration code

Scope:
- `src/arena/runtime`
- architecture tests
- import smoke tests if needed

Acceptance criteria:
- `arena.core` and `arena.games` do not import `arena.runtime`, `arena.match`, or `arena.adapters`
- `arena.match` does not import `arena.runtime` or `arena.adapters`
- `arena.adapters` does not import `arena.runtime`
- `arena.runtime` may depend on `arena.core`, `arena.match`, and `arena.adapters.in_process`
- no API, persistence, subprocess, timeout, auth, matchmaking, tournament, or rendering dependencies are introduced

#### Slice 2 - Runtime domain models

Objective:
- define the pure runtime data model before implementing execution behavior

Scope:
- match ids
- player records
- lifecycle states
- runtime events
- abort metadata
- runtime exceptions

Acceptance criteria:
- match ids are opaque string values
- caller-provided ids are supported
- default id generation is available as a convenience helper
- player records include `player_id`, optional `label`, and `seat`
- lifecycle can distinguish `created`, `running`, `finished`, and `aborted`
- abort metadata can capture a stable reason code, message, and optional cause type/message
- runtime exceptions do not modify or replace `arena.core` domain exceptions
- runtime events describe orchestration facts and do not duplicate game-domain events

#### Slice 3 - Arena and local session execution

Objective:
- add a small pure in-memory `Arena` coordinator for local runtime sessions

Scope:
- create local sessions from a game definition, config, players, and optional match id
- bind in-process payload policies separately from player identity
- start, step, and run local sessions by delegating to `arena.match` and `arena.adapters.in_process`

Acceptance criteria:
- `Arena` can create a session in `created` state
- a session can transition to `running` and own a `LocalMatch`
- a session can advance one turn by requesting an action from the bound policy for the current seat
- a session can run until the underlying game reaches a rule result
- missing policy, adapter failure, bad payload, and illegal returned action become runtime aborts
- core exceptions are preserved as causes rather than hidden by generic errors
- no networking, persistence, subprocesses, deadlines, auth, matchmaking, tournaments, or rendering logic are added

#### Slice 4 - Runtime transcript and UI-ready payload envelopes

Objective:
- expose stable runtime-level data envelopes for CLI demos, human-readable transcript formatting, and future UI work

Scope:
- runtime transcript envelope
- session status payload
- player/seat payloads
- runtime event payloads
- explicit transcript validation helper

Acceptance criteria:
- runtime transcript wraps the existing `dump_match_transcript(...)` output instead of changing the match transcript schema
- runtime transcript includes match id, game id, lifecycle, players, runtime events, abort metadata when present, and the inner match transcript when available
- session status payload exposes enough information for a UI to show match id, game id, lifecycle, current seat, players, turn count, result, and latest snapshot without needing direct access to `LocalMatch`
- payloads are JSON-safe and stable
- no UI rendering, component state, transport, or persistence assumptions are introduced
- validation of the wrapped match transcript remains explicit

Status:
- completed through Slice 4

Implementation note:
- added `arena.runtime` with opaque match ids, player records, lifecycle states, runtime events, abort metadata, runtime exceptions, a pure in-memory `Arena` coordinator, local `MatchSession` execution, explicit runtime abort boundaries, wrapped runtime transcripts, and UI-ready session status payloads
- updated architecture tests to preserve dependency direction: core/games cannot import match/adapters/runtime, match cannot import adapters/runtime, adapters cannot import runtime, and runtime may depend downward on core/match/adapters
- added focused runtime unit tests covering session creation, start/step/run, missing-policy aborts, illegal-action aborts preserving core causes, adapter failures, lifecycle errors, status payloads, and explicit runtime transcript validation

Handoff note:
- see `docs/MATCH_ARENA_HANDOFF.md`

### Phase 21 - Runtime / UI contract stabilization

Objective:
- stabilize the pure runtime payload contract before building UI code

Decision inputs:
- `arena.runtime` now owns match ids, player records, lifecycle, runtime events, abort metadata, local session execution, wrapped transcripts, and session status payloads
- the upcoming UI should consume stable JSON-safe data, not direct `LocalMatch` internals
- UI rendering decisions must not leak into `arena.core`, `arena.games`, `arena.match`, or rule engines

Scope:
- `arena.runtime` payload contracts
- payload shape tests
- docs and examples for runtime status/transcript usage
- compatibility/version validation for runtime envelopes

Out of scope:
- FastAPI or WebSocket APIs
- remote agents
- subprocess management
- persistence
- stale-version handling
- deadlines and timeout outcomes
- authentication and authorization
- matchmaking queues
- tournaments
- concrete UI components or rendering logic

Questions to answer first:
- what exact fields does the first UI need for the match screen?
- is `latest_snapshot` sufficient for board rendering, or should runtime expose an additional game-neutral view model?
- should runtime status include the latest runtime event list, or should events stay transcript-only?
- should payload shape stability be asserted through full-dictionary tests, JSON Schema emission, or both?
- how should UI distinguish game-domain events from runtime events?
- should README include runtime examples before any UI package exists?

Acceptance criteria:
- `dump_session_status(...)` exposes a stable, JSON-safe status contract for UI and CLI consumers
- `dump_runtime_transcript(...)` remains a wrapper around the existing match transcript and includes runtime metadata
- runtime payload schema versions are validated explicitly
- tests cover running, finished, and aborted session payloads
- tests cover player labels, current seat, turn count, result, latest snapshot, abort metadata, and event payloads
- no rendering, transport, persistence, or remote-agent assumptions are introduced

Status:
- ready for next-session planning and implementation

#### Slice 1 - Status/transcript contract checkpoint `[done]`

Objective:
- lock the first pure runtime payload contract for UI and CLI consumers without introducing rendering helpers or board-specific view models

Status:
- completed

Implementation note:
- stabilized `dump_session_status(...)` with an explicit runtime status schema version and a matching validation helper
- kept `latest_snapshot` as the authoritative rendering-agnostic state payload instead of adding a game-neutral derived board view
- kept runtime events out of session status while making runtime transcript events self-identify with `event_scope="runtime"`
- tightened the payload models so runtime status and transcript schemas encode the fixed supported `schema_version` value `1`
- added full-payload stability tests for running, finished, and aborted session status payloads plus explicit version validation for both status and transcript envelopes

Handoff note:
- see `docs/MATCH_ARENA_HANDOFF.md`

### Phase 22 - Human-readable transcript and CLI demo helpers

Objective:
- validate the runtime/UI contract through simple human-readable local output before adding a UI

Scope:
- pure formatting helpers or demo-facing utilities for runtime status and transcript payloads
- README or docs examples showing local runtime execution
- focused tests for deterministic human-readable output

Out of scope:
- command-line argument parsing unless explicitly planned
- network APIs
- persistence
- subprocess agents
- UI rendering
- remote agents
- matchmaking or tournaments

Candidate responsibilities:
- format player/seat assignments
- format lifecycle, current turn, result, and abort status
- format turn history from the wrapped runtime transcript
- include runtime events without duplicating game-domain events
- keep all authoritative data in runtime payloads, with human-readable output derived from them

Acceptance criteria:
- a completed local Connect 4 runtime session can be rendered as deterministic readable text
- an aborted session can be rendered with abort reason and cause metadata
- formatting helpers consume payloads or runtime transcript data rather than direct mutable internals
- tests assert representative output without overfitting to cosmetic wording

Status:
- completed

Implementation note:
- added pure runtime formatting helpers that consume stabilized session status and runtime transcript payloads
- supported deterministic readable output for completed and aborted local sessions, including player/seat assignments, lifecycle, current or terminal status, result/abort metadata, runtime events, and turn history
- kept runtime events in the top-level runtime transcript section and game-domain events in per-turn history formatting
- added focused formatter tests plus README-backed demo coverage without adding CLI parsing, UI rendering, transport, persistence, remote agents, or broader infrastructure

### Phase 23 - UI adapter boundary

Objective:
- define the first thin boundary between pure runtime payloads and the upcoming UI

Scope:
- UI-facing adapter models or helpers that reshape runtime payloads without changing simulation/runtime authority
- docs describing what a UI may consume and what remains internal
- architecture tests if a new package is introduced

Out of scope:
- FastAPI or WebSocket APIs unless a later phase explicitly adds transport
- persistence
- remote agents
- auth
- matchmaking
- tournaments
- embedding UI rendering logic inside simulation, match, or runtime rules

Candidate responsibilities:
- map runtime status payloads into screen-level data structures
- preserve stable identifiers for match, players, seats, turns, and lifecycle
- keep board rendering data derived from snapshots or a documented view payload
- prepare for eventual UI work without committing to a transport or framework

Acceptance criteria:
- the UI adapter depends downward on `arena.runtime`
- `arena.runtime`, `arena.match`, `arena.core`, and `arena.games` do not depend on the UI adapter
- adapter outputs remain JSON-safe and deterministic
- no web server, database, subprocess, auth, or matchmaking code is introduced

Status:
- completed

Implementation note:
- added a pure `arena.ui` package that validates runtime status/transcript envelopes and reshapes them into deterministic screen-level payloads for status, transcript/history, and combined match-screen consumers
- preserved runtime snapshots as authoritative while exposing only an opaque `state_payload` convenience mapping derived from each snapshot state for future board rendering
- kept runtime events top-level and game-domain events inside turn history, sorted players by seat for deterministic output, and added architecture tests enforcing the UI adapter depends only on `arena.runtime` within the arena package
- added focused tests for running, created, finished, and aborted status payloads; transcript event separation and turn ordering; combined screen mismatch rejection; schema-version constants; JSON round-tripping; and unknown runtime payload fields

### Phase 24 - First concrete UI surface (terminal replay viewer)

Objective:
- prove that `arena.ui.build_match_screen(...)` is sufficient to render a real match screen by adding a pure terminal renderer that consumes the runtime/UI payload contract end-to-end without introducing transport, persistence beyond a single JSON file, subprocesses, deadlines, auth, matchmaking, live human play, or remote agents

Scope:
- new `arena.cli` package containing pure rendering helpers and a small frame-stepping entrypoint
- per-game board renderers in `arena.cli.games.connect4` and `arena.cli.games.tictactoe` that read the opaque `state_payload` from `arena.ui`
- a small `examples/` script that runs a scripted match, dumps `dump_session_status(...)` and `dump_runtime_transcript(...)` to disk, and re-renders the saved payloads
- focused unit tests for renderer determinism plus an architecture test that pins import direction
- README and handoff updates

Out of scope:
- web servers, HTTP/WebSocket transport, or any networking
- persistence beyond reading and writing one JSON file in `examples/`
- subprocess or remote agents
- deadlines, timeouts, auth, matchmaking, tournaments
- live human play (covered in Phase 25)
- TUI frameworks beyond plain stdout
- a game-neutral board view inside `arena.runtime` or `arena.ui`

Design decisions (locked before slicing):
- the renderer reads only `arena.ui` screen payloads; it does not access `LocalMatch`, rules engines, or game internals beyond `state_payload`
- session status reflects the latest state only; the transcript provides historical turn data, and the renderer never reconstructs intermediate status payloads at older turns
- renderer output uses ANSI color escape sequences for board cells and headers, with deterministic sequences so golden tests remain stable
- match-running helpers that produce sample transcripts live in `examples/`, not inside `arena.cli`
- after Phase 24, Phase 25 will introduce live human play (`HumanPolicy`) before any transport adapter

Acceptance criteria:
- a scripted Connect 4 and a scripted Tic-Tac-Toe match can be run, dumped to JSON, and re-rendered as deterministic readable terminal output
- the renderer is a pure function of the payloads
- architecture tests prevent any upper layer from depending on `arena.cli`
- no transport, persistence layer beyond `json.dump`/`json.load`, no subprocesses, no human input loop

#### Slice 1 - `arena.cli` package boundary and architecture test

Objective:
- create the `arena.cli` package as the first surface that may consume `arena.ui`, and lock the dependency direction with an architecture test

Scope:
- `src/arena/cli/__init__.py` with no runtime symbols beyond an explicit empty `__all__`
- `src/arena/cli/games/__init__.py` placeholder
- new architecture test asserting that `arena.core`, `arena.games`, `arena.match`, `arena.adapters`, `arena.runtime`, and `arena.ui` do not import `arena.cli`
- update existing import-boundary tests if needed so they keep passing alongside the new package

Acceptance criteria:
- the package imports cleanly under the existing test runner
- `arena.cli` may import `arena.ui` and `arena.runtime` (and `arena.games.*` only when needed for game ids), but every layer below is forbidden from importing `arena.cli`
- ruff and pytest both pass

#### Slice 2 - Generic screen renderer

Objective:
- add a pure renderer that converts a screen payload from `arena.ui.build_match_screen(...)` into deterministic ANSI-colored terminal text covering the static screen chrome (without per-game board art)

Scope:
- `src/arena/cli/rendering.py` exposing `render_match_screen(screen_payload: Mapping[str, Any]) -> str`
- header rendering: match id, game id, lifecycle, current seat, turn count
- player roster rendering sorted by seat (label + seat + active indicator)
- result and abort rendering for finished and aborted screens
- runtime events list rendering (top-level), distinct from per-turn game events
- turn-by-turn summary section rendering seats and actions only (no board yet)
- ANSI color usage encapsulated in small constants, reset codes always emitted, no third-party color library
- focused tests for running, finished, and aborted screen payloads asserting the rendered string matches a stable golden output (color escapes included)

Acceptance criteria:
- output is deterministic byte-for-byte for the same payload
- the renderer does not import `arena.match`, `arena.adapters`, `arena.core`, or any game package
- ruff and pytest pass

#### Slice 3 - Per-game board renderers

Objective:
- add Connect 4 and Tic-Tac-Toe board renderers that read the opaque `state_payload` from screen payloads, plus a dispatch in the generic renderer keyed on `game_id`

Scope:
- `src/arena/cli/games/connect4.py` exposing `render_board(state_payload: Mapping[str, Any]) -> str`
- `src/arena/cli/games/tictactoe.py` exposing `render_board(state_payload: Mapping[str, Any]) -> str`
- registry mapping `{ "connect4": ..., "tictactoe": ... }` resolved inside `rendering.py` via a small dispatch helper
- the generic renderer inserts the rendered board immediately after the header for running and finished screens, omits it for created/aborted screens where no snapshot is available
- ANSI colors per disc/mark; consistent monospace grid; column headers for Connect 4
- golden tests for representative empty, mid-game, and terminal boards for both games
- a fallback path so unknown game ids render without a board instead of failing

Acceptance criteria:
- both board renderers are pure and depend only on the payload mapping
- output is deterministic byte-for-byte
- dispatch never imports the game package's typed modules beyond what is required for game-id constants
- ruff and pytest pass

#### Slice 4 - Transcript file loader and frame entrypoint

Objective:
- add a small loader that reads a status JSON file plus a transcript JSON file, validates them through `arena.ui`, and renders one or all frames; expose a tiny `python -m arena.cli` entrypoint for ad-hoc viewing

Scope:
- `src/arena/cli/app.py` with a `render_session_from_files(status_path, transcript_path, *, turn: int | None = None) -> str` helper
- `src/arena/cli/__main__.py` that parses `--status`, `--transcript`, and optional `--turn` and prints the rendered output
- "all frames" mode iterates each turn in transcript order and prints headers separating turn N output
- frame N rendering keeps status reflecting the latest state and changes only the per-turn summary cursor; the board for an intermediate frame is rendered from that turn's `post_snapshot.state`
- focused tests for the helper covering frame 0, mid-game frame, terminal frame, and the all-frames mode
- the entrypoint is covered indirectly by helper tests; module-level argparse wiring stays minimal

Acceptance criteria:
- the helper validates input through the existing `arena.ui` validators and surfaces validation errors as exceptions
- output is deterministic
- no new dependencies are added; only stdlib `json` and `argparse`
- ruff and pytest pass

#### Slice 5 - Examples script, README example, and handoff update

Objective:
- prove the end-to-end flow with a scripted example, document the new viewer in the README, and update the handoff for Phase 25

Scope:
- `examples/run_and_render_match.py` that builds a Connect 4 (or Tic-Tac-Toe) session with scripted policies, runs it through `Arena.run_session(...)`, dumps both payloads to JSON files, and prints the rendered final frame
- README section showing how to run the example and how to use `python -m arena.cli`
- `docs/MATCH_ARENA_HANDOFF.md` updated with Phase 24 status and the Phase 25 (live human play / `HumanPolicy`) recommendation
- `docs/NEXT_SESSION_PROMPT.md` refreshed to reflect Phase 24 completion and Phase 25 next steps

Acceptance criteria:
- the example script runs end-to-end without errors and produces both JSON payload files plus rendered output
- README shows the example and the entrypoint
- handoff and next-session prompt mention Phase 25 explicitly
- ruff and pytest pass

### Phase 25 - Live human play (terminal)

Objective:
- let a human take a seat in a local runtime session and play against a scripted opponent through the terminal, exercising the runtime step loop and validating the abort path under realistic interactive conditions, without introducing networking, persistence beyond writing the final transcript, subprocesses, deadlines, auth, matchmaking, GUI, or remote agents

Scope:
- new `arena.cli.policies` module containing `HumanPolicy` plus per-game input parsers added to the existing `arena.cli.games.<game>` modules
- new `arena.cli.play` module containing an interactive driver and a `python -m arena.cli.play` entrypoint
- focused unit tests for input parsing, the driver loop, the abort path, and a full end-to-end Connect 4 game with fake stdin
- README and handoff updates

Out of scope:
- networking, HTTP/WebSocket transport
- persistence beyond writing the final transcript JSON files
- subprocesses, remote agents, LLM-backed agents
- deadlines, timeouts, auth, matchmaking, tournaments
- GUI or TUI frameworks beyond plain stdout
- simultaneous human players on different machines

Design decisions (locked before slicing):
- `HumanPolicy` lives in `arena.cli.policies`; it is a typed-observation in-process policy that delegates parsing to a per-game callable and retries on bad input
- the CLI driver renders the screen between turns; `HumanPolicy` itself does not render
- per-game parsers are pure functions returning the typed action or `None` to retry; they live next to the renderers in `arena.cli.games.<game>`
- Connect 4 input is a single integer column index; Tic-Tac-Toe uses numpad-style `1-9` with `1` = top-left, `9` = bottom-right
- `q`, `quit`, EOF, and `KeyboardInterrupt` abort the session through the runtime abort path with stable reason codes (`user_quit`, `user_interrupt`); they do not exit the process directly
- bad input never aborts the session; the policy reprompts until the human provides a syntactically valid line that parses to a legal action
- the driver is a single blocking function with `stdin`/`stdout` injection so tests can feed pre-baked input queues
- inline action specs are accepted for scripted seats on the command line; no JSON action files
- the interactive driver does not replace `examples/run_and_render_match.py`; non-interactive demos stay there
- the existing simulation invariant holds: transcripts replay deterministically given the recorded actions, regardless of who chose them

Acceptance criteria:
- a human can play a full Connect 4 game against a scripted opponent through `python -m arena.cli.play`
- bad and out-of-range inputs reprompt without affecting the session
- `q` / `quit` / EOF / Ctrl-C produce a runtime abort with a clear reason and a non-zero exit code, with the abort block rendered in red
- on terminal completion, status and transcript JSON files are written to `--out-dir` and the final frame is printed
- transcript replay through `validate_runtime_transcript(...)` continues to succeed for a completed human-vs-scripted match
- `arena.core`, `arena.games`, `arena.match`, `arena.adapters`, `arena.runtime`, and `arena.ui` do not import `arena.cli`
- ruff and pytest pass

#### Slice 1 - `HumanPolicy` and per-game input parsers

Objective:
- add the typed in-process human policy and pure per-game input parsers without touching the driver loop yet

Scope:
- `src/arena/cli/policies.py` exposing `HumanPolicy` and a small `HumanQuit` sentinel exception
- new `parse_input(line, observation)` callables in `src/arena/cli/games/connect4.py` and `src/arena/cli/games/tictactoe.py`
- focused tests using `io.StringIO` stdin and a captured stdout: legal input, illegal syntax retry, out-of-range retry, full Connect 4 column retry, illegal Tic-Tac-Toe cell retry, `q` and EOF raising `HumanQuit`, KeyboardInterrupt also raising `HumanQuit`

Acceptance criteria:
- parsers are pure functions returning the typed action or `None` to signal retry
- `HumanPolicy` calls the parser, reprompts on `None`, raises `HumanQuit` on quit/EOF/KeyboardInterrupt
- no rendering, no session, no runtime imports beyond what is needed for typed observation/action types

#### Slice 2 - Interactive driver and `python -m arena.cli.play` entrypoint

Objective:
- add the interactive driver that creates a session, renders, steps, and exits cleanly on terminal or abort, plus a small CLI entrypoint that wires up game/seat/policy choices

Scope:
- `src/arena/cli/play.py` exposing `play_match(definition, config, players, policies, *, out_dir, stdin=sys.stdin, stdout=sys.stdout) -> int`
- the driver renders the screen between turns, calls `Arena.step_session(...)`, catches `HumanQuit` and `KeyboardInterrupt` and routes them through the runtime abort path with reason codes `user_quit` and `user_interrupt`, and writes status/transcript JSON files on terminal or abort
- `src/arena/cli/play/__main__.py` (or a `__main__` block in `play.py`) accepting `--game {connect4,tictactoe}`, `--seat-0`, `--seat-1` (`human` or `scripted:0,1,0,...`), `--out-dir`, plus optional Connect 4 config flags
- inline scripted seat specs parse to a small in-process policy that emits the listed actions in order
- focused tests driving a full Connect 4 game with a fake stdin queue against a scripted opponent, asserting deterministic final rendered output and transcript file existence; tests for the abort paths (`q` mid-game, EOF mid-game) asserting non-zero return code, abort block rendered, and aborted-lifecycle status payload on disk

Acceptance criteria:
- the driver is a single blocking function; tests run it with injected `stdin`/`stdout`
- abort paths produce a runtime-aborted session with the correct reason code preserved in the dumped status payload
- the entrypoint prints rendered output to stdout and writes both JSON files
- ruff and pytest pass

#### Slice 3 - Architecture test refresh, README, and handoff update

Objective:
- keep import boundaries tight, document the new entrypoint, and prepare the handoff for Phase 26 (LLM-backed agent through the existing typed payload adapter)

Scope:
- update `tests/unit/architecture/test_cli_boundaries.py` if Slices 1-2 introduce new submodules; the prohibition that nothing below `arena.cli` imports `arena.cli` stays in force
- README: new "Play locally" section showing a `python -m arena.cli.play --game connect4 --seat-0 human --seat-1 scripted:0,1,0,1,0,1,0` example and a one-paragraph note on quit/abort semantics
- `docs/MATCH_ARENA_HANDOFF.md`: Phase 25 status section and Phase 26 recommendation pointing at an Anthropic-SDK-backed `InProcessAgent` wrapped by the existing `TypedPayloadPolicyAdapter`
- `docs/NEXT_SESSION_PROMPT.md`: refreshed current-status paragraph and Phase 26 as the next slice

Acceptance criteria:
- architecture tests still pass and still forbid upward imports from `arena.cli`
- README and handoff docs reflect the live-play entrypoint and the Phase 26 direction
- ruff and pytest pass

### Phase 26 - Local LLM agent (Ollama)

Objective:
- add a local LLM-backed agent so two Ollama models can play a deterministic perfect-information match against each other (or against a human or scripted seat) through the existing typed in-process adapter, without introducing remote API keys, networking transport, persistence, subprocess orchestration, deadlines, auth, or matchmaking

Scope:
- new `arena.agents.ollama` package containing a stdlib HTTP client, an `OllamaAgent` implementing the typed agent contract, per-game prompt builders/parsers, and typed exceptions
- new additive runtime event `PolicyRetried` so retry-with-feedback iterations show up in transcripts without leaking agent internals into runtime models
- CLI extension: a third seat type `ollama:<model>` plus `--ollama-host`, `--ollama-temperature`, `--ollama-seed`, `--ollama-max-retries` flags
- model availability probe at CLI startup so missing models fail fast with a clear message
- runnable example using `llama3.2:latest` vs `qwen2.5:1.5b` on a small Connect 4 board
- README section, handoff doc, and architecture test for the new package

Out of scope:
- Anthropic / OpenAI / any remote-API agent (deferred to Phase 27)
- async or streaming responses
- subprocess orchestration of the model server
- timeouts beyond a single per-request HTTP timeout
- persistence beyond writing the final transcript JSON files
- new transport layer (HTTP to Ollama is local stdlib `urllib`, in-process from the runtime's perspective)
- model fine-tuning, tournament infrastructure, or evaluation harnesses

Design decisions (locked before slicing):
- the agent is a typed `InProcessAgent` wrapped by the existing `TypedPayloadPolicyAdapter`; no new adapter contract, no parallel runner
- HTTP is stdlib `urllib.request` only; no `httpx`, no `requests`, no `aiohttp`; no new third-party dependencies
- prompts always include both the ASCII rendered board (via existing `arena.cli.games.<game>.render_board`) and the structured JSON snapshot, plus the legal-actions list
- response parsing uses Ollama's `format` JSON-schema constraint to force structured output; the parsed dict is rehydrated via the game serializer's `load_action` path where possible
- on illegal action, the agent retries up to 3 times by default with the rejection reason and the legal-actions list re-injected; after exhaustion it raises `OllamaIllegalActionError`, which becomes a runtime abort with `AbortReason.ADAPTER_ERROR` and an informative cause message
- retry attempts emit a new additive `PolicyRetried` runtime event via a callback the agent receives at construction so `arena.agents` does not import runtime internals
- determinism by default: `temperature=0` and a fixed `seed` (default `0`) so transcript replay reproduces the same chosen actions; both are CLI-overridable
- model availability is probed once via `/api/tags` at CLI startup before the session is created; missing models exit non-zero with a clear message naming what to pull
- architecture rule extended: `arena.core`, `arena.games`, `arena.match`, `arena.adapters`, `arena.runtime`, `arena.ui`, and `arena.cli` do not import `arena.agents`; `arena.agents` may import `arena.core`, game-specific serializers, and the existing public `arena.cli.games.<game>.render_board` helpers

Acceptance criteria:
- the documented CLI command runs an end-to-end match against a real local Ollama daemon when both models are pulled
- with the daemon unreachable or a model missing, the entrypoint fails fast with a clear non-zero exit and a message naming the missing model or host
- agent retry attempts on illegal model output are visible as `PolicyRetried` runtime events in the dumped transcript
- after the configured retry budget is exhausted, the session aborts with `ADAPTER_ERROR` and the abort metadata cause message includes the model id and the last invalid action
- `examples/run_ollama_vs_ollama.py` runs the full flow and writes status/transcript JSON
- architecture tests prevent any non-`arena.agents` package from importing `arena.agents`
- ruff and pytest pass

#### Slice 1 - Ollama HTTP client + `OllamaAgent` shell + retry loop

Objective:
- add the package skeleton, a stdlib HTTP client, and the generic typed agent with retry-with-feedback logic; no game-specific code yet

Scope:
- `src/arena/agents/__init__.py` (empty `__all__`)
- `src/arena/agents/ollama/__init__.py` exposing `OllamaAgent`, `OllamaIllegalActionError`, `OllamaUnavailableError`, `OllamaModelMissingError`, `probe_models`
- `src/arena/agents/ollama/client.py` with `OllamaClient` wrapping `POST /api/chat` and `GET /api/tags` via `urllib.request`, with configurable timeout and host
- `src/arena/agents/ollama/agent.py` with `OllamaAgent` implementing the typed agent contract, holding `(client, model, prompt_builder, max_retries, seed, temperature, retry_callback)`
- a `PromptBuilder` Protocol describing the interface Slice 2 must implement
- `src/arena/agents/ollama/exceptions.py` with the three typed exceptions
- new tests under `tests/unit/agents/ollama/` using a stub transport (no real HTTP) covering: legal response, illegal-then-legal recovery emitting a retry callback, exhausted retries raising `OllamaIllegalActionError`, daemon unreachable, model missing
- new `tests/unit/architecture/test_agents_boundaries.py` enforcing the dependency direction

Acceptance criteria:
- the package imports cleanly and exposes the documented surface
- agent loop works against a stub `PromptBuilder` and stub `OllamaClient` injected at construction
- retry callback fires once per retry, never on the first attempt or the final success
- architecture test passes
- ruff + pytest pass

#### Slice 2 - Per-game prompt builders and parsers

Objective:
- implement `Connect4PromptBuilder` and `TicTacToePromptBuilder` so the generic `OllamaAgent` from Slice 1 can play both built-in games

Scope:
- `src/arena/agents/ollama/connect4.py` with deterministic system + user prompt templates and a JSON-schema response spec
- `src/arena/agents/ollama/tictactoe.py` same shape, using the existing public `numpad_action` helper for action rehydration
- prompts include: short rules block, the rendered ASCII board, the structured JSON snapshot, the legal-actions list, and a labeled retry-feedback section when present
- parsers reject malformed responses by returning `None` so the agent retries; never by raising
- new tests with golden prompt strings and parser behavior coverage on legal / illegal / malformed responses

Acceptance criteria:
- prompt rendering is deterministic byte-for-byte
- parsers handle malformed responses by returning `None`, not by raising
- a stubbed transport emitting canned legal moves can complete a full Connect 4 game in tests
- ruff + pytest pass

#### Slice 3 - Runtime event, CLI wiring, example, and docs

Objective:
- expose retries in the transcript, wire the new seat type into the CLI, ship a runnable example, and document the flow

Scope:
- new `PolicyRetried` runtime event in `src/arena/runtime/models.py` with fields `match_id`, `seat`, `attempt`, `reason_summary`; additive change consistent with the existing `USER_QUIT` precedent; included in the runtime event union and reflected in transcript payload schemas without bumping `schema_version`
- a small public helper in `arena.runtime` so the agent's callback does not reach into runtime internals
- CLI extension in `src/arena/cli/play/__main__.py`: parse `ollama:<model>` seat specs, plus `--ollama-host`, `--ollama-temperature`, `--ollama-seed`, `--ollama-max-retries` flags with the locked defaults; construct `OllamaAgent` wrapped in `TypedPayloadPolicyAdapter`
- startup probe: when at least one Ollama seat is configured, call `probe_models(host)` and fail fast on missing daemon or models
- `examples/run_ollama_vs_ollama.py` runs `llama3.2:latest` vs `qwen2.5:1.5b` on Connect 4 (rows=4, cols=4, connect_length=4), dumps payloads, prints final frame; importable `run()` function with smoke test that uses a stubbed client
- README: "Watch two LLMs play" section showing the CLI command, model-pull prerequisites, and the `PolicyRetried` runtime event note
- `docs/MATCH_ARENA_HANDOFF.md` and `docs/NEXT_SESSION_PROMPT.md` updated for Phase 26 completion and Phase 27 (Anthropic-SDK-backed agent reusing `PromptBuilder`) as the next step

Acceptance criteria:
- a stubbed end-to-end test (no real Ollama) drives `play_match` with two `OllamaAgent`s, completes a small Connect 4 match, and dumps a transcript whose runtime events include at least one `PolicyRetried` from a forced retry path
- a stubbed daemon-unreachable test on the CLI returns non-zero with a clear message
- all existing tests still pass
- ruff + pytest pass

Status:
- completed (Slices 1-3 shipped; the local Ollama vs Ollama Connect 4 flow runs end-to-end through `python -m arena.cli.play`)

### Remote-play roadmap (Phases 27 - 35)

Phase 26 closes the "everything in one process" branch of the roadmap. The remaining phases pivot to remote play: a WebSocket server, a typed reference SDK, two local Ollama agents connecting to a publicly reachable server as the v1 acceptance demo, plus the resilience and observability needed to call v1 "solid". This block lifts the long-standing bans on networking, deadlines, and remote agents in a controlled order.

The locked decisions that drive Phases 27 - 35:
- transport is WebSocket only; wire format is JSON; no MessagePack/Protobuf option
- per-turn deadlines live in `arena.server`, never in `arena.runtime`; expiry produces an existing-style runtime abort
- match identity uses unguessable opaque ids (`secrets.token_urlsafe(16)` >=128 bits of entropy), and possession of the id is the only capability in v1 (no auth)
- the creator becomes seat 0; the joiner becomes seat 1; the unguessable `match_id` is the invite token
- `MatchRegistry` is in from day one; there is no "single hardcoded match" intermediate step
- the SDK ships both a `connect(...)` callback form and a lower-level `Session` loop form so future MCP layering does not require an SDK redesign
- the SDK ships the Connect 4 / Tic-Tac-Toe Pydantic schemas directly; clients do not fetch schemas at handshake
- `docs/NETWORK_PROTOCOL.md` is the language-agnostic source of truth; the Python SDK is a reference implementation, not the spec
- structured JSON logging lives in `arena.server` only; metrics endpoints, Prometheus, and OpenTelemetry tracing are deferred to v2
- v2 deferrals (out of scope for Phases 27 - 35): web spectator UI, transcript persistence beyond stdout/file, real auth, Anthropic-SDK-backed agent, Prometheus metrics, OpenTelemetry tracing, lobby/matchmaking, third-party game registration, TypeScript SDK port, MCP server unless explicitly built in Phase 35
- v1 acceptance demo: two local Ollama agents on the user's laptop both connect to a publicly reachable `arena.server` instance, complete one clean Connect 4 match, and complete one deliberate-abort scenario (one peer killed mid-turn)

New layer rules introduced by this block:
- new packages: `arena.adapters.websocket`, `arena.server`, `arena.sdk`
- existing layer rules continue to hold; `arena.core`, `arena.games`, `arena.match`, `arena.runtime`, and `arena.ui` must not import any of the three new packages
- `arena.adapters.websocket` is a sibling of `arena.adapters.in_process`; it depends only on `arena.core` payload types and pure `arena.adapters.in_process` payload models
- `arena.server` may depend on `arena.runtime`, `arena.adapters.in_process`, `arena.adapters.websocket`, and `arena.ui`; nothing else may import `arena.server`. `arena.server` exposes a `GET /schemas/payloads` endpoint serving the canonical JSON Schema bundle described in `docs/NETWORK_PROTOCOL.md` §17 so non-Python SDKs can codegen against the same source of truth
- `arena.sdk` may depend on `arena.core` (for game schemas) and `arena.adapters.websocket` (for envelope types); it must not import `arena.match`, `arena.adapters.in_process`, `arena.runtime`, `arena.ui`, `arena.cli`, or `arena.server`
- structured logging at module-load scope is allowed only in `arena.server`; lower layers may use `logging` only inside functions and only when explicitly opted in
- `arena.cli` may consume `arena.sdk` so the existing `python -m arena.cli.play` entrypoint can drive remote sessions through `--server-url`

### Phase 27 - Network protocol design checkpoint

Objective:
- lock the wire protocol, glossary, error taxonomy, and layer rules before any networking code is added, so every subsequent slice has a single source of truth to implement against

Scope:
- `docs/NETWORK_PROTOCOL.md`
- updates to `CLAUDE.md`, `AGENTS.md`, `docs/ADAPTER_BOUNDARIES.md`, `docs/MATCH_ARENA_HANDOFF.md`, `docs/NEXT_SESSION_PROMPT.md` reflecting the lifted bans, the new packages, and the new layer rules
- this `IMPLEMENTATION_PLAN.md` block (Phases 27 - 35)
- no source code, no tests touching `src/`

Out of scope:
- any code under `src/arena/server`, `src/arena/sdk`, or `src/arena/adapters/websocket`
- HTTP routes, FastAPI wiring, `websockets` library integration
- new architecture tests (those land with the packages they protect)
- web spectator UI work
- Anthropic / OpenAI / remote-API agents
- any v2 deferrals listed in the roadmap intro

Acceptance criteria:
- `docs/NETWORK_PROTOCOL.md` exists and covers: transport, URL shape, lifecycle, envelope, schema-versioning policy, every message type with payload fields, error taxonomy with WebSocket close codes and in-band error codes, match creation/join flow, disconnect/reconnection rules, idempotency model, rate limits, logging contract, conformance test contract, forward-compatibility notes
- the protocol doc declares itself the language-agnostic source of truth and labels the Python SDK as a reference implementation
- `CLAUDE.md` no longer claims "no networking, persistence, subprocesses, timeouts, auth, matchmaking, remote agents, or UI rendering yet"; the layer table includes `arena.adapters.websocket`, `arena.server`, and `arena.sdk` with their responsibilities; the rule that timeouts live only in `arena.server` is recorded
- `AGENTS.md` records the same rule changes
- `docs/ADAPTER_BOUNDARIES.md` describes `arena.adapters.websocket` as a sibling to `arena.adapters.in_process` and documents what each may import
- `docs/MATCH_ARENA_HANDOFF.md` and `docs/NEXT_SESSION_PROMPT.md` point at Phase 28 as the next entry point
- ruff + pytest pass (no source changes)

Status:
- in progress (Slice 1 first pass shipped; revised after adversarial review with the following additions: full HTTP request/response shapes for `POST /matches`, `GET /matches/{id}`, `GET /games`; explicit `per_action_retry_budget`, `per_turn_deadline_ms`, `disconnect_grace_ms` lifecycle owned by match creation; `resume_token` scoped server-side to `(match_id, seat)` and rotated on every resume; deterministic ordering of `action_rejected(0)` -> `match_state(aborted)` -> `match_aborted` -> close on retry-budget exhaustion; atomicity rule for `running -> finished/aborted` transitions; per-connection FIFO + per-`turn_id` retry-counter decrement semantics; per-match concurrent-connection cap; new §17 "Payload reference" exposing `GET /schemas/payloads` for non-Python SDK codegen; new §18 "Message broadcast matrix"; explicit v1 information-model assumption restricting the protocol to public-move perfect-information games; replaced "byte-identical replay" with "logically equivalent state". The first three CRITICAL findings (resume-token seat takeover, retry budget undefined, unspecified payload schemas) are closed by the revision; the remaining findings are either accepted as v1 trust-model decisions or already addressed)

#### Slice 1 - Protocol document and doc updates

Objective:
- ship the protocol doc and propagate the new rules to the existing meta-docs in one reviewable change

Scope:
- create `docs/NETWORK_PROTOCOL.md`
- update `CLAUDE.md`, `AGENTS.md`, `docs/ADAPTER_BOUNDARIES.md`, `docs/MATCH_ARENA_HANDOFF.md`, `docs/NEXT_SESSION_PROMPT.md`
- append Phases 27 - 35 to `IMPLEMENTATION_PLAN.md`

Acceptance criteria:
- the protocol doc passes its own internal completeness checklist (every message type from the taxonomy is described, every close code is listed, every layer rule is traceable to the locked decisions above)
- meta-doc updates do not contradict each other or the protocol doc
- ruff + pytest pass

### Phase 28 - `arena.adapters.websocket` payload contract

Status: Slice 1 complete — envelope models, discriminated union, codec, and full test suite shipped; all acceptance criteria met; ruff + pytest pass.

Objective:
- add the typed wire-envelope contract as a sibling adapter to `arena.adapters.in_process`, without introducing any I/O, server, or client code

Scope:
- new package `src/arena/adapters/websocket/` containing only Pydantic v2 envelope models and discriminated-union message-type validators, plus pure JSON encode/decode helpers
- focused unit tests covering: envelope round-trips for every message type, schema-version validation, malformed-envelope rejection, additive-optional forward compatibility
- new architecture test extending the existing import-boundary suite to forbid lower layers from importing `arena.adapters.websocket`

Out of scope:
- any networking code, including imports of `websockets`, `aiohttp`, `httpx`, FastAPI, or the stdlib `socket`/`asyncio.network` surface
- server or client implementations
- timeouts, heartbeats, reconnection logic
- match creation HTTP routes

Acceptance criteria:
- every protocol message type from `docs/NETWORK_PROTOCOL.md` has a Pydantic envelope model that round-trips JSON byte-for-byte against representative fixtures
- `schema_version` is enforced to `1` in v1 with a clear error on mismatch
- payload bodies for `observation_request`, `action_response`, and `action_rejected` re-use the existing `arena.adapters.in_process` payload models verbatim (no copy-paste)
- architecture tests prove `arena.core`, `arena.games`, `arena.match`, `arena.runtime`, and `arena.ui` do not import `arena.adapters.websocket`
- ruff + pytest pass

#### Slice 1 - Envelope models and discriminated union

Status: complete.

Scope:
- envelope base model with the fields documented in protocol §6
- one Pydantic model per message type from §8
- `dumps(envelope) -> str` and `loads(text) -> Envelope` helpers using stdlib `json`
- focused unit tests

Acceptance criteria:
- every protocol message type has a model and a passing round-trip test
- unknown envelope fields are accepted and ignored
- unknown payload fields inside known message types are accepted and ignored
- binary input to `loads` raises a clean typed error

### Phase 29 - `arena.server` skeleton with `MatchRegistry`

Status: Complete. Slice 1 shipped HTTP surface, `MatchRegistry`, and `create_app`. Slice 2 shipped the WebSocket play handler, runtime bridge, and 10 focused unit tests. Slice 3 shipped real-TCP integration tests (ephemeral-port uvicorn fixture + async WS client helper): Connect 4 happy path, Tic-Tac-Toe happy path, and malformed-envelope protocol test. All 541 tests pass; ruff clean.

Objective:
- ship the smallest WebSocket server that can host a Connect 4 or Tic-Tac-Toe match between two scripted Clients end-to-end, with `MatchRegistry` and `POST /matches` from day one

Scope:
- new package `src/arena/server/` containing: `app.py` (FastAPI app), `registry.py` (`MatchRegistry`, `Match`), `routes_http.py` (`POST /matches`, `GET /matches/{id}`, `GET /games`), `routes_ws.py` (the play WS handler), `runtime_bridge.py` (glue between an `Arena` session and the WS handler), `__main__.py` (`python -m arena.server`)
- in-process integration test infrastructure: pytest fixture spawning the FastAPI app on an ephemeral port and a small async WS test client
- new architecture test forbidding lower layers from importing `arena.server`
- one happy-path Connect 4 integration test driving two scripted Clients through real WebSocket frames against a real running server

Out of scope:
- timeouts and heartbeats (Phase 32)
- reconnection and resume tokens beyond a stub (Phase 32)
- structured JSON logging (Phase 33)
- TLS, deployment recipes, Dockerfile (Phase 34)
- the SDK (Phase 30)
- Ollama integration (Phase 31)

Acceptance criteria:
- `python -m arena.server --host 127.0.0.1 --port 8080` boots the server
- `POST /matches` with a valid `game_id` and `game_config` returns `{match_id, seat_0_url, seat_1_url}` with a `match_id` of >=128 bits of entropy
- `GET /games` returns the registered game ids and their config schemas via existing `Serializer.config_schema()`
- two test Clients can connect to the seat URLs, complete a Connect 4 match, and validate the resulting transcript through `validate_runtime_transcript(...)`
- malformed envelopes close the offending connection with code `4422`
- `arena.core`, `arena.games`, `arena.match`, `arena.adapters.*`, `arena.runtime`, `arena.ui`, `arena.cli`, and `arena.sdk` do not import `arena.server`
- ruff + pytest pass

#### Slice 1 - HTTP surface and `MatchRegistry`

Status: complete.

Scope:
- `MatchRegistry` holding `Match` records keyed by id; `Match` owns its `Arena` session, its registered `GameDefinition`, its current connections, and its lifecycle
- HTTP routes: `POST /matches`, `GET /matches/{id}`, `GET /games`
- focused unit tests for the registry and route validation

Acceptance criteria:
- `POST /matches` validates the requested `game_id` and `game_config` through the registered serializer; rejects unknown game ids with HTTP 400; rejects invalid configs with the existing domain error
- `POST /matches` accepts and validates `per_turn_deadline_ms`, `per_action_retry_budget`, and `disconnect_grace_ms` per protocol §4.1; defaults match the doc; out-of-range values return HTTP 400 `invalid_request`
- `match_id` generation uses `secrets.token_urlsafe(16)`
- `GET /games` exposes config schemas without importing `arena.server` from any lower layer
- `GET /schemas/payloads` returns the JSON Schema bundle defined in protocol §17, byte-stable for `schema_version=1`

#### Slice 2 - WebSocket play handler

Status: complete.

Scope:
- `WS /matches/{id}/play?seat=N` handler implementing the `hello` -> `welcome` handshake, the per-turn `observation_request` -> `action_response` loop, and the terminal `match_finished` / `match_aborted` messages
- runtime bridge that pulls observations from the session's bound `Arena.step_session(...)` and pushes them as envelopes; routes `action_response` back through `apply_payload_policy_turn(...)`
- close-code coverage for `4400`, `4404`, `4409`, `4422`

Acceptance criteria:
- two scripted test Clients complete a Connect 4 match through real WebSocket frames against an ephemeral-port server
- close codes match the protocol doc on every documented failure path

#### Slice 3 - Integration test infrastructure

Status: complete.

Scope:
- pytest fixture for an ephemeral-port server lifecycle (start, yield base URL, stop)
- minimal async WS test client helper using `websockets` or `httpx`'s WS support
- one Connect 4 happy path test, one Tic-Tac-Toe happy path test, one malformed-envelope test

### Phase 30 - `arena.sdk` reference Python client

Objective:
- ship a Python SDK that lets a user write `def choose(obs): ...` and connect to a running `arena.server` with one call, plus a lower-level `Session` loop form so future MCP layering does not require an SDK redesign

Scope:
- new package `src/arena/sdk/` containing: `client.py` (`connect(...)` callback form, `Session` class loop form), `types.py` (re-exports of game schemas + envelope models), `errors.py` (typed wire-error hierarchy mapping protocol error codes to exceptions), `testing.py` (`LocalSession` test helper that runs the protocol in-memory without a real WS)
- focused unit tests using `LocalSession` for the SDK itself; one integration test that runs the SDK against the real `arena.server` from Phase 29
- new architecture test forbidding `arena.sdk` from importing `arena.match`, `arena.adapters.in_process`, `arena.runtime`, `arena.ui`, `arena.cli`, or `arena.server`

Out of scope:
- TypeScript port (v2)
- MCP wrapper (Phase 35)
- reconnection logic beyond surfacing dropped sessions (Phase 32 finishes resume)
- agent-side telemetry of any kind

Acceptance criteria:
- the documented `connect(url, seat, choose=...)` callback form completes a Connect 4 match against the real server end-to-end with a scripted callback
- the `Session` loop form is exercised by a test that drives the same match using `recv()` / `send_action(...)` calls
- typed errors (`IllegalActionError`, `WrongSeatError`, `MatchAbortedError`, `ProtocolError`, `SchemaVersionError`, `MatchNotFoundError`) cover every protocol error code
- `LocalSession` lets a user unit-test their `choose(...)` callback without spinning up a server
- the SDK ships Connect 4 and Tic-Tac-Toe schemas via re-export of existing `arena.core`/`arena.games` Pydantic models without copy-paste

#### Slice 1 - `Session` loop form and `LocalSession`

Scope:
- `Session.connect(url, seat, *, resume_token=None) -> Session` opening the WS, performing the handshake, and exposing `recv()` and `send_action(...)`
- `LocalSession` implementing the same surface against an in-memory protocol simulator backed by `arena.runtime`
- focused unit tests using `LocalSession` against scripted match scripts

#### Slice 2 - `connect(...)` callback form

Scope:
- thin wrapper turning `Session.recv()` -> dispatch -> `Session.send_action(...)` into a single call with a user-supplied `choose(observation) -> action` callback
- handles `match_finished` and `match_aborted` by returning the final transcript to the caller
- focused unit tests using `LocalSession`

#### Slice 3 - Integration test against real server

Scope:
- one test that spawns the Phase 29 server, calls `arena.sdk.connect(...)` from two scripted Clients, completes a Connect 4 match, and validates the transcript

### Phase 31 - Ollama-over-WS port and CLI `--server-url`

Objective:
- prove the SDK abstraction is right by running the existing `OllamaAgent` over the wire with zero changes to the prompt/parse code, and let `python -m arena.cli.play` connect to a remote server

Scope:
- new `arena.cli.remote` (or equivalent) module that wires `arena.agents.ollama.OllamaAgent` into `arena.sdk.connect(...)` via its existing `choose(observation)` shape
- extend `arena.cli.play.__main__` with a `--server-url` flag; when present, the named seat connects to the remote server instead of running in-process
- one stubbed end-to-end test (no real Ollama, scripted moves) running two `OllamaAgent`s through the SDK against a real `arena.server` instance, completing a small Connect 4 match
- README section "Play remotely with Ollama" showing the local-only quickstart

Out of scope:
- TLS deployment (Phase 34)
- timeouts and reconnection (Phase 32)
- the public-internet acceptance demo (Phase 34)

Acceptance criteria:
- `python -m arena.cli.play --game connect4 --seat-0 ollama:llama3.2 --seat-1 ollama:qwen2.5 --server-url ws://127.0.0.1:8080` runs both agents against a local `arena.server`
- the `OllamaAgent` source code is unchanged from Phase 26 (only the wiring is new)
- the stubbed test passes deterministically and validates the resulting transcript

### Phase 32 - Resilience: timeouts, aborts, reconnection

Status: ✅ COMPLETE

Objective:
- make the server survive the failure modes that appear once real network and real LLMs are in the loop, without leaking any deadline logic into `arena.runtime`

Scope:
- per-turn deadline configured at match creation; server-side timer per `observation_request`; expiry triggers a runtime abort with reason `turn_deadline_expired` (the abort itself stays in `arena.runtime`, the deadline lives in `arena.server`)
- disconnect grace period (default 30s) for the active seat; off-turn disconnects keep the match alive until the dropped seat's turn arrives
- WS heartbeats: server pings every 20s, two missed `pong`s closes with `4408`
- action idempotency via per-match committed-`turn_id` set; duplicate `action_response` messages are dropped silently
- resume protocol: `hello.resume_token` lets a reconnecting Client receive the latest lifecycle and a transcript replay before normal flow resumes
- new tests covering each failure path documented in protocol §15
- SDK reconnect helper using the resume token

Out of scope:
- TLS (Phase 34)
- structured logging (Phase 33)
- multi-match resilience scenarios beyond the existing `MatchRegistry`
- persistence across server restarts (a stale `resume_token` correctly returns `4410`)

Acceptance criteria:
- the conformance test suite from protocol §15 passes for the server ✅
- `arena.runtime` source still contains no deadline logic; deadline enforcement lives entirely in `arena.server` ✅
- the SDK exposes a documented reconnection path; the integration test reconnects mid-match and finishes successfully ✅
- ruff + pytest pass ✅

#### Slice 1 - Per-turn deadline and timeout abort

Status: complete.

#### Slice 2 - Disconnect grace and resume protocol

Status: complete.

#### Slice 3 - Heartbeats and idempotency

Status: complete.

### Phase 33 - Server observability baseline (structured logging)

Objective:
- ship structured JSON logs from the server so debugging "what happened in match X" is a `grep` away, without introducing metrics, tracing, or any v2 telemetry

Scope:
- `arena.server.logging` configuring `structlog` (added as a dependency) with a JSON formatter writing to stdout
- one structured log line per documented event in protocol §14; required fields enforced by a test
- new architecture test forbidding lower layers from instantiating loggers at module-load scope (functions inside `arena.core`, `arena.games`, `arena.match`, `arena.adapters.*`, `arena.runtime`, `arena.ui`, `arena.cli`, `arena.sdk` may use `logging` lazily, but must not call `logging.getLogger(__name__)` at module scope)
- README "Operating the server" section documenting how to capture, rotate, and grep logs

Out of scope:
- Prometheus metrics (v2)
- OpenTelemetry tracing (v2)
- match transcripts in logs (transcripts go to their own channel)
- agent-side logging in the SDK (the SDK stays silent unless the user opts in via standard Python logging config)

Acceptance criteria:
- every event listed in protocol §14 is emitted at least once across the test suite, with all required fields present
- the architecture test catches any new lower-layer module-scope logger
- the SDK produces zero log output by default in the integration tests

### Phase 34 - Public deployment and acceptance demo

Objective:
- prove v1 is solid by running the documented acceptance demo: two local Ollama agents on the user's laptop, both connecting to a publicly reachable `arena.server`, completing one clean match and one deliberate-abort scenario

Scope:
- `Dockerfile` building the server image
- `docs/DEPLOYMENT.md` describing the Caddy reverse-proxy recipe (`wss://` termination), Fly.io / small-VM deployment example, environment variables, and the `python -m arena.server` entrypoint
- README "Watch two LLMs play remotely" section showing both the run-it-locally and connect-to-public-server flows
- acceptance demo script under `examples/run_remote_demo.py` that runs two local Ollama agents against a configurable `--server-url`, dumps both transcripts, and prints the final frames
- focused tests where feasible (in-process server + scripted agents); the public-server run is documented but exercised manually
- updates to `docs/MATCH_ARENA_HANDOFF.md` and `docs/NEXT_SESSION_PROMPT.md` recording the v1 milestone

Out of scope:
- TLS terminated by `arena.server` itself (always done by reverse proxy)
- managed deployment to a specific provider beyond a single Fly.io example
- transcript persistence beyond writing to disk in `examples/`
- a friend physically running the agent on their machine (supported by the same code path; not required for the v1 bar because of the local-Ollama-only constraint)

Acceptance criteria:
- the user can run `examples/run_remote_demo.py --server-url wss://...` against a deployed server and watch two local Ollama agents play
- one deliberate-abort scenario (one agent process killed mid-turn) leaves the server with an `aborted` transcript whose `validate_runtime_transcript(...)` succeeds and whose abort metadata reason is `peer_disconnected`
- the README quickstart for the remote demo is reproducible
- ruff + pytest pass

### Phase 35 - MCP server layer (optional v1 extension)

Objective:
- expose the SDK through an MCP server so Claude Desktop and other MCP clients can join matches as agents, without changing the wire protocol or the SDK

Scope:
- new `arena-mcp-server` package (or `src/arena/mcp/`) implementing MCP tools `join_match`, `get_observation`, `make_move`, `get_history`, `match_status` on top of `arena.sdk.Session`
- one stubbed end-to-end test driving the MCP tools against a stub MCP client and a real `arena.server`
- README "Play with Claude Desktop" section

Out of scope:
- everything else listed under v2 deferrals

Acceptance criteria:
- the documented MCP tools complete a small Connect 4 match against a real server when invoked in sequence
- `arena.sdk` source code is unchanged
- v1 acceptance does not require Phase 35; if skipped, Phase 35 stays open without blocking the v1 milestone

Status (Phases 27 - 35):
- Phase 27 in progress (this document update + protocol doc + meta-doc updates)
- Phases 28 - 35 not started
