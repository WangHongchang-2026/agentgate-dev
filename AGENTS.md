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

Every architecture/refactor progress response begins with a short `Where are we` block.
