# Regression-set Workflow Design Record

## Status

Implemented and verified on `feature/regression-set`. This record captures stable design
decisions; delivery scope, file ownership, checkpoints, and acceptance tests are owned by
[the implementation plan](regression-set-plan.md).

## Context

The roadmap places single-Case rerun and regression-set workflow under Delivery Stage 3,
Result Center and Regression. A failed or important Case must be reusable across Agent
versions without changing its historical Run or creating a second evaluation engine.

## Decision

Model a regression set as a normal versioned Dataset with `purpose=regression`:

```text
completed RunSnapshot Case
  -> copied Case + immutable provenance
  -> regression Dataset draft
  -> published DatasetVersion
  -> existing Evaluation Setup and RunEngine
```

The Dataset stores test content only. Agent version, Evaluators, MetricPlan, and GateSpec
are selected by each Run and are not bound to the regression Dataset.

## Source and Identity Rules

- The source is resolved only from a completed RunSnapshot.
- The copied Case gets a new internal ID.
- `provenance.source_case_id` preserves source identity.
- One source Case can appear at most once in one regression Dataset.
- The same source Case may appear in different regression Datasets.
- Different source IDs with identical content are allowed.
- Normal Cases may omit provenance.

## Version and Persistence Rules

- Regression Datasets reuse one active draft and immutable published versions.
- Adding to a published Dataset first creates the next draft from the latest version.
- New Dataset and initial draft creation is one SQLite transaction.
- Non-null provenance is part of published content hashing.
- Old payloads without purpose or provenance remain readable as standard Dataset data.
- No SQL table migration is required because Dataset records are JSON payloads.

## Execution Boundary

Regression purpose does not change execution behavior. A Run explicitly selects a
published DatasetVersion and embeds it in RunSnapshot. RunEngine, Trace, Evaluators,
Results, Metrics, and Gate remain unchanged.

After publication, navigating to Evaluation Setup refreshes the Dataset catalog so the
new version can be selected. This is a UI synchronization requirement, not a Dataset
domain rule.

## Error Rules

- Unknown Run, Case, or Dataset is a resource error.
- Non-completed Run, invalid target mode, archived/standard target, draft execution, and
  duplicate membership are configuration errors.
- These errors occur before evaluation and are never represented as Agent FAIL.
- Persistence failure must not leave a partial Dataset, draft, or membership.

## Consequences

Benefits:

- regression Cases use the same authoring, validation, versioning, and execution path;
- historical evidence remains immutable and traceable;
- no evaluator or RunEngine coupling is introduced;
- later Agent versions can run identical published inputs.

Trade-offs:

- this increment does not compare complete Runs automatically;
- provenance increases DatasetVersion content and is retained with the Case;
- users must explicitly review and publish before execution.

## Deferred Decisions

The broader Result Center plan must define Case correction, result filtering,
confusion-matrix source data, and whole workflow integration. A/B comparison, automatic
badcase promotion, optimizer suggestions, external target write-back, and scheduler
behavior remain owned by their roadmap plans.
