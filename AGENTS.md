# Project context

This repository contains a Python 3.11 library for turn-based game simulation, built incrementally for an agent-vs-agent arena project.

Current scope is intentionally narrow:
- strictly sequential games
- deterministic games
- perfect-information games
- simulation package first
- no arena/server code in the initial implementation

The first concrete game is Connect 4.

**REMEMBER TO ACTIVATE THE VIRTUAL ENVIRONMENT `.venv` IN THE BASE ROOT BEFORE RUNNING ANY SCRIPT**


# Main architectural principles

- Keep layers strictly separated.
- The simulation core must remain pure and reusable.
- Do not mix game rules with transport, persistence, UI, or orchestration concerns.
- Prefer small, composable modules over premature framework-like abstractions.
- Implement only what is needed now, but shape interfaces so they can be reused later.

# Core design decisions

- Use **frozen dataclasses** for in-memory domain state and actions.
- Use **Pydantic** for config models, external payloads, serialization-facing models, and JSON Schema emission.
- Use **typed Python domain objects internally**. Do not normalize everything into dicts/JSON inside the simulation core.
- Serialize only at the boundary through dedicated serializer components.
- Use **integer seat ids** in the simulation core.
- Agent names and display labels belong to adapters/UI layers, not the simulation layer.
- Store authoritative state only; derive convenience data on demand where possible.
- `apply_action(...)` must validate defensively and re-check legality.
- Keep orchestration concerns outside the simulation package.

# Intended module split

The codebase should evolve around these separated responsibilities:

- `GameDefinition`
  - static metadata
  - validated game config
  - game registration / lookup
- `RulesEngine`
  - initial state creation
  - legal action generation
  - action validation
  - state transitions
  - terminal/result logic
- `Serializer`
  - state/action/config serialization
  - JSON-safe payload conversion
  - rehydration from serialized snapshots
- `Observation`
  - player-facing view of state
  - separate abstraction even if, for now, it mirrors full state
- domain events
  - emitted by the simulation layer when meaningful rule events occur

# What belongs in the simulation package

Allowed:
- game state
- actions
- rules
- observations
- game config
- game definition / registry
- serializers
- pure domain events
- shared generic test contract

Not allowed:
- FastAPI
- WebSockets
- DB access
- matchmaking
- auth
- timeouts
- stale-move handling
- agent connection logic
- UI rendering logic
- infrastructure concerns

# Error handling expectations

Use rich typed domain exceptions where appropriate.

Examples:
- `WrongPlayer`
- `IllegalAction`
- `GameFinished`
- `InvalidConfig`

Do not introduce orchestration-specific exceptions such as stale-version handling into the pure simulation layer.

# Serialization expectations

- Serialized snapshots must be rehydratable.
- Each successful move should eventually correspond to a full serialized post-move snapshot.
- The initial state must also be serializable as a snapshot.
- Prefer explicit, stable serializer code over ad-hoc `dict` construction spread across the codebase.

# Testing expectations

Testing is mandatory, not optional.

Every game implementation should support a shared generic test contract covering at least:
- valid initial state
- valid legal action generation
- rejection of illegal actions
- correct state transition behavior
- terminal/result consistency
- serialization round-trip / rehydration

Add focused unit tests close to the game logic being introduced.

# Connect 4 baseline

Connect 4 is the first implementation and should be treated as the reference vertical slice for the library architecture.

For Connect 4:
- board is stored internally as a tuple of tuples
- actions represent only the move itself
- seats are integers
- game is sequential, deterministic, and perfect-information
- start with one main phase only
- expose structured legal actions, not action masks

# Implementation style

- Favor clarity over cleverness.
- Keep functions small and explicit.
- Avoid hidden side effects.
- Prefer pure transformations and immutable state updates.
- Do not introduce speculative abstractions for future games unless they already reduce duplication now.
- Keep public interfaces intentional and stable.
- Use type hints consistently.

# Working workflow for this repository

When implementing work:
1. follow `IMPLEMENTATION_PLAN.md`
2. expand only the current section into concrete subtasks
3. implement the smallest coherent slice
4. add/update tests
5. verify behavior
6. update the implementation plan if needed
7. then move to the next slice

Do not skip ahead and do not rewrite unrelated modules without a clear reason.

# If unsure

When uncertain, preserve:
1. separation of concerns
2. purity of the simulation core
3. typed internal models
4. minimal authoritative state
5. testability