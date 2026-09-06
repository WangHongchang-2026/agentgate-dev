# AgentGate Project Instructions

## Architecture And Refactor Workflow

For each top-level package, folder, or module being designed or refactored, use these
approval checkpoints in order:

1. **Names and structure:** propose or apply only folder and filename changes, then show
   the resulting tree to the user for confirmation.
2. **Responsibilities:** review one file at a time and agree on its purpose and ownership.
3. **Detailed design:** for that confirmed file, agree on classes, functions, protocols,
   relationships, invariants, and dependencies.
4. **Implementation:** implement only the confirmed file design, add or update focused
   tests, and show verification results before moving to the next file.

Do not combine these checkpoints or continue to the next checkpoint without explicit
user confirmation. When the user asks only to review names, do not redesign or implement
classes. During file-level review, discuss and implement one file at a time.

## Goal Mode Workflow

The normal approval checkpoints above remain the default. They are waived only when an
active Goal explicitly authorizes autonomous implementation and identifies the approved
scope and completion condition.

While working under such a Goal:

- Continue through file-level design, implementation, and verification without waiting
  for additional user confirmation.
- Read the relevant implementation plans before changing code and stay within their
  approved architecture and ownership boundaries.
- Assess `goal/p1-demo`, `integration/p1-new`, and the current refactor before implementing
  each capability. Record whether behavior or ideas are reused, adapted, or written from
  scratch; reuse never means blindly copying code.
- Keep changes in small, coherent checkpoints and run focused tests after each checkpoint.
  Run the required full regression before declaring the Goal complete.
- Update `docs/project-progress.md` and affected implementation plans as work is completed.
- Preserve unrelated work and avoid destructive operations, compatibility layers, and
  unplanned architecture changes.
- Commit or push only when the Goal explicitly authorizes those actions, and only after
  the relevant verification passes.
- Stop and request user input only when blocked by missing credentials or external access,
  a destructive or irreversible action, conflicting requirements, or a product or
  architecture decision not covered by the Goal and approved plans.

A Goal is complete only when its stated end-to-end behavior works, required tests pass,
documentation reflects the result, and no required work within its scope remains.

## Project Baseline

- `goal/p1-demo` is the behavior-preservation baseline.
- `docs/architecture.md` is the target structural authority.
- `docs/refactor-implementation-plan.md` is the refactor execution map.
- `integration/p1-new` is a team member's reference branch, not the refactor base.
- Preserve unrelated and uncommitted work; never include it in a refactor commit.
- `refactor-1` is a clean break for internal and external contracts. Do not add legacy
  aliases, dual schemas, payload migration validators, or deprecated API fields unless the
  user explicitly requests a migration path.

Every architecture/refactor progress response begins with a short `Where are we` block.

## Engineering Philosophy

Follow a Unix-style design: each component has one clear responsibility, explicit inputs
and outputs, and can be composed with other components.

- Prefer composition over inheritance. Do not build concrete-class hierarchies for
  feature reuse; shared domain inheritance is limited to the technical `DomainModel` base.
- Keep domain objects as immutable data plus local invariants. Put workflows and external
  effects in their owning capability or integration module.
- Use a `Protocol` only at a real execution or integration boundary with multiple
  implementations.
- Prefer small functions and focused modules, but do not create wrapper classes or files
  that add no invariant, lifecycle, or meaningful behavior.
- Avoid factories, registries, plugin frameworks, event buses, and generic service layers
  until demonstrated implementations require them.
- Compose evaluator and pipeline behavior through explicit references, ordered inputs,
  and returned values rather than hidden hooks or subclass overrides.
- Keep stable concepts typed. Use versioned configuration or extensible identifiers only
  for details expected to evolve frequently.

## Coding Style

- Prefer plain functions for transformations and orchestration. Introduce a class only
  when the data has meaningful invariants, identity, lifecycle, or stateful behavior.
- Do not create passive wrapper classes for a few fields when those fields have no
  independent invariant or reuse.
- Keep dependencies explicit through parameters and return values. Avoid hidden global
  state, implicit registration, and import-time side effects.
- Use typed models for stable business contracts. Use dictionaries only for genuinely
  open-ended JSON configuration, metadata, or external payloads.
- Use enums or literals for closed values that control behavior. Use validated strings for
  business labels and extension points expected to grow without core-code changes.
- Domain code must not depend on API, UI, storage, scheduler, or integration code. Invalid
  domain states should be rejected when the object is constructed.
- Do not implement a capability until it has a real producer and consumer. Record future
  extension points in documentation instead of adding unused fields or abstractions.
- Prefer precise business names such as `EvaluationResult` over generic names such as
  `Result`, `Data`, `Manager`, or `Service` when a more specific concept exists.
- Keep comments short and use them only for non-obvious constraints or decisions. Do not
  narrate straightforward code.
- Tests should verify public behavior, domain invariants, serialization boundaries, and
  failure cases. Do not couple tests to private implementation details.
