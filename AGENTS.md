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
