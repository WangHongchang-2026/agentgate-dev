# Result

The Result capability owns deterministic conclusions and descriptive summaries derived
from completed evaluation Runs.

## Ownership and Structure

```text
result/
├── analytics.py
├── comparison.py
├── gate.py
├── metrics.py
└── report.py
```

Pure calculations belong in `result/`. Domain Result models belong in `domain/`.
Read-only retrieval and assembly for Web, CLI, and APIs belongs in
`application/result_reader.py`. The cross-capability failed-Case workflow belongs in
`application/result_case_writeback.py`. Persistence belongs in `storage/`, and optional
external delivery belongs in `integrations/result_outputs/`.

Result does not execute Evaluators, invoke Agents, collect Traces, mutate Dataset
publications, diagnose root causes, or render Web charts.

## Gate and Report Rules

- `MetricPlan` selects a versioned algorithm; unsupported versions fail explicitly.
- Metric keys are machine identifiers. Localized labels belong to the Web layer.
- One metric key cannot be assigned to multiple quality dimensions in one Run.
- `metrics.py` is the only source of calculated scores. `gate.py` consumes the overall
  metric instead of calculating another score.
- `gate.py` fails closed when primary Results are missing, reviewed, errored, contain a
  blocking failure, or provide no applicable score. Individual not-applicable Results do
  not block a Run that still has a valid applicable score.
- Gate decisions carry a typed reason code; the Web layer owns translated display text.
- Result counts live in Metrics rather than being duplicated on the Gate decision.
- Metrics do not expose an ambiguous `incomplete` flag: evaluator errors use the `errors`
  count, while missing expected Results use `ReleaseGateDecision.missing_results`.
- `report.py` assembles a completed Run, Results, Metrics, and release-gate decision.
- `EvaluationReport` validates Result identities and evaluator metadata against the
  immutable `RunManifest`, including the expected Case-by-primary-Evaluator matrix.

## Analytics

`analytics.py` calculates read-time Result distributions by Evaluator, Case category,
difficulty, tag, observed Skill route, Tool-use expectation, and failure type.

- Evaluator, category, difficulty, and tag buckets aggregate `EvaluationResult` records.
- Routing and Tool-use buckets aggregate correlated `CheckResult` records only when the
  Run contains the corresponding typed expectations and checks.
- Failure buckets use the primary failure stage or sanitized Evaluator-error category.
- Optional dimensions are marked unavailable when their evidence does not exist.
- A tagged Result participates in every tag bucket on its Case, so tag totals can overlap.
- `average_score` is a descriptive arithmetic mean and does not replace the official
  score produced by the Run's `MetricPlan`.
- Analytics do not cluster failures or produce root causes and suggestions; those
  responsibilities belong to the Optimizer.

## Historical Cases and Writeback

The failed-Case workflow is:

```text
failed Run
→ exact Case snapshot from the Run manifest
→ edited Case copy
→ current or new Dataset draft
→ publish as a new Dataset version
→ launch a new Evaluation using that version
```

The workflow enforces these rules:

- Only Cases selected for the source Run can be opened through the historical Case API.
- Only a Case with at least one failed Result can be written back.
- The edited Case keeps the historical Case ID.
- An existing Dataset draft is reused without removing its other Cases.
- When no draft exists, the latest published Dataset version is used as the draft base.
- The source Run manifest and all published Dataset versions remain unchanged.

Writeback updates a draft only. Publication remains an explicit Dataset operation, and
starting another Evaluation remains an explicit Run operation.

## HTTP API

The Result routes expose:

```http
GET  /api/overview
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/analytics
GET  /api/runs/{run_id}/cases/{case_id}
GET  /api/runs/{run_id}/traces/{case_id}
POST /api/runs/{run_id}/cases/{case_id}/writeback
```

Publishing the resulting draft uses
`POST /api/datasets/{dataset_id}/drafts/publish`. Starting an Evaluation for the newly
published Dataset version uses `POST /api/evaluations`.

## Rerun Semantics

`POST /api/runs/{run_id}/rerun` creates a new Run with the exact historical manifest,
including its original Dataset version and Case selection. It is intended for reproducible
re-execution of unchanged inputs.

After correcting a Case and publishing a new Dataset version, callers must use
`POST /api/evaluations` with that new version. AgentGate does not persist a separate
Regression Case set.

## Current Delivery Boundary

The historical Case, writeback, and analytics backend and API contracts are implemented.
The Result Center Web interface is intentionally deferred. Writeback does not
automatically publish the draft or start another Run.

See [project progress](../project-progress.md) for the broader delivery sequence.
