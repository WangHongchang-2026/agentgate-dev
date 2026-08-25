# Regression-set Workflow Plan

## 1. Goal

Allow a developer to preserve a Case from a completed evaluation as a reusable
regression Dataset, review and publish it, and execute the published version through the
normal evaluation workflow.

```text
Completed Run
  -> select Case
  -> copy from immutable RunSnapshot into regression Dataset draft
  -> review and publish DatasetVersion
  -> select the published regression Dataset in Evaluation Setup
  -> Run -> Trace -> Result -> Metric -> Gate
```

This increment is complete when the workflow succeeds through the API and Chinese Web UI
on desktop and mobile, while existing Dataset and evaluation workflows remain green.

## 2. Current State and Gap

Implemented and verified on `feature/regression-set`:

- `DatasetPurpose` distinguishes standard and regression Datasets while preserving old
  payload compatibility;
- `CaseProvenance` records the immutable source Run, Dataset version, Case, capture time,
  and optional reason;
- a Case from a completed Run can be added to a new or existing regression Dataset draft;
- duplicate source Cases are rejected within the same regression Dataset;
- regression Datasets reuse draft validation, immutable publication, RunEngine, reports,
  and Trace;
- the evaluation page refreshes its Dataset catalog when opened, so a newly published
  regression Dataset can be selected and run;
- unit, API, type, build, desktop, and mobile acceptance tests pass.

Remaining gaps belong to the broader Result Center capability: Case correction from a
Result, result filtering, confusion-matrix source data, and whole-Run comparison. There is
no incompatible persisted POC data; old payloads load with standard defaults.

## 3. Scope and Non-Goals

In scope:

- explicit regression Dataset identity;
- copying one snapshotted Case into a new or existing regression Dataset draft;
- immutable source provenance and duplicate prevention;
- review, edit, validate, publish, and normal evaluation of the regression Dataset;
- API and Web workflows with deterministic tests.

Non-goals:

- automatic population from every failure;
- editing the source Run, Result, Trace, or published DatasetVersion;
- binding Agent, Evaluator, MetricPlan, or GateSpec to a regression Dataset;
- regression-specific execution engines, schedulers, queues, or release gates;
- whole-Run comparison, A/B winner decisions, clustering, or confusion matrices;
- automatic correction or write-back to an external Agent platform.

## 4. Terms

```text
Regression Dataset
  A Dataset whose purpose is regression. It contains Cases selected for repeated checks.

Source Case
  The Case stored inside the completed source RunSnapshot.

Regression Case
  A copy with a new Case ID and immutable provenance pointing to the Source Case.

Membership
  Presence of one Source Case in one Regression Dataset.

Draft
  Editable candidate for the next DatasetVersion; never executable.

Published DatasetVersion
  Immutable content selected by a Run.
```

A regression Dataset is an evaluation asset, not an evaluation configuration or a Run.

## 5. Ownership and Dependencies

- `domain/case.py` owns Dataset purpose and Case provenance meaning.
- `case/` owns Dataset drafts, versions, validation, and Case editing.
- `control_plane/` owns the add-to-regression workflow composition.
- `server/` exposes application operations without duplicating domain rules.
- `run/` consumes a published DatasetVersion and remains unaware of regression purpose.
- `web/` coordinates user interaction and delegates validation to APIs.
- `storage/` persists Dataset and DatasetVersion payloads atomically.

The workflow consumes completed RunSnapshot content and existing Result presentation. It
must not mutate Run, Trace, Result, published DatasetVersion, or external Agent assets.

## 6. Domain and Data Model

```text
Dataset
  purpose: standard | regression        default: standard

Case
  provenance: CaseProvenance | null     default: null

CaseProvenance
  source_type: run_result
  source_run_id
  source_dataset_id
  source_dataset_version
  source_case_id
  captured_at
  reason
```

Rules:

- Dataset purpose is fixed at creation.
- Regression Case content is copied from `RunSnapshot.dataset.cases`.
- The copied Case receives a new internal ID.
- Provenance is immutable and included in new DatasetVersion hashes.
- Missing purpose/provenance fields retain compatibility with old payloads.
- Membership is unique by `(regression_dataset_id, source_case_id)`.
- SQLite continues to store JSON payloads; no table migration is required.

## 7. Behavior and State Transitions

```text
completed Run + source Case
        |
        +--> new regression Dataset -> initial draft
        |
        +--> existing regression Dataset
                 +--> active draft -> append
                 +--> no draft -> create from latest published version -> append

draft -> validate -> published DatasetVersion -> normal evaluation Run
```

Only completed Runs are accepted. The source Case is resolved from the immutable
RunSnapshot, not a current Dataset draft. Adding to a new Dataset persists Dataset and
initial draft in one transaction. Adding to an existing Dataset updates one effective
draft. A validation failure produces no partial membership.

Evaluation-page navigation refreshes the catalog before the user selects a newly
published version. Execution ordering, timeout, retry, and cancellation remain owned by
the normal Run lifecycle; this increment introduces none of its own.

## 8. Error and Outcome Semantics

| Condition | Semantics |
| --- | --- |
| Unknown Run, Case, or Dataset | `404` resource error |
| Source Run not completed | `422` configuration error |
| Draft selected for execution | `422` configuration error |
| Standard or archived target Dataset | `422` configuration error |
| Both/neither target modes supplied | `422` request error |
| Duplicate source Case in one regression Dataset | `422` membership conflict |
| Persistence failure | server error and atomic rollback |
| Agent/evaluator failure during later Run | normal Result outcome rules |

Membership errors are not evaluator FAILs. Evaluator ERROR remains distinct from Agent
FAIL, as required by the project architecture.

## 9. Security and Resource Limits

- Treat Case input, expected values, notes, and provenance reason as untrusted data.
- Apply existing Pydantic and Dataset publication validation before persistence/use.
- Do not copy credentials, raw private configuration, or unrelated Result/Trace payloads
  into provenance.
- Do not accept arbitrary filesystem or network references in this workflow.
- Reuse Dataset size and Case-count limits defined by Dataset management.
- UI error messages expose actionable validation details but not stack traces or secrets.
- Retention follows Dataset/Run persistence policy; this increment adds no independent
  retention or background work.

## 10. API and UI

API:

```text
POST /api/runs/{run_id}/cases/{case_id}/regression
```

The request selects exactly one target: an existing `regression_dataset_id`, or a new
Dataset name with optional description. An optional reason is stored in provenance. The
response contains the Dataset, updated draft, and copied Case.

UI:

1. A completed Run report shows one `加入回归集` action per Case.
2. The dialog selects an existing regression Dataset or creates a new one.
3. The original report remains unchanged after submission.
4. Dataset management shows purpose and read-only provenance.
5. The user reviews and publishes the draft.
6. The evaluation page reloads published Dataset options on navigation.
7. The user selects Agent, regression Dataset version, and Evaluators, then starts the
   normal evaluation.

The UI does not decide membership, duplicate, version, or execution rules.

## 11. File Change Map

```text
[MOD]  src/agentgate/domain/case.py
[MOD]  src/agentgate/domain/__init__.py
[MOD]  src/agentgate/case/service.py
[MOD]  src/agentgate/control_plane/service.py
[MOD]  src/agentgate/server/application.py
[MOD]  src/agentgate/storage/base.py
[MOD]  src/agentgate/storage/sqlite.py
[MOD]  src/agentgate/case/import_export.py
[MOD]  web/src/types/dataset.ts
[MOD]  web/src/api/client.ts
[MOD]  web/src/api/datasets.ts
[MOD]  web/src/App.vue
[MOD]  web/src/pages/DatasetWorkspace.vue
[MOD]  web/src/components/dataset/DatasetList.vue
[MOD]  web/src/components/dataset/CaseEditor.vue
[MOD]  web/src/style.css
[ADD]  tests/test_regression_set.py
[ADD]  tests/test_regression_set_api.py
[MOD]  tests/test_dataset_import_export.py
[MOD]  web/tests/demo.spec.ts
[MOD]  web/tests/dataset.spec.ts
[ADD]  docs/dataset/regression-set-design.md
[ADD]  docs/dataset/regression-set-plan.md
[KEEP] RunEngine, evaluator execution, Result aggregation, MetricPlan, and GateSpec
[KEEP] SQLite table layout; no SQL migration
```

## 12. Parallel Development Boundary

- Branch/workstream: `feature/regression-set`.
- Base dependency: `feature/single-case-rerun` and the current Dataset contracts.
- This workstream owns the files listed above only for regression-specific changes.
- Evaluator algorithms and expectation semantics remain owned by the Evaluator
  workstream.
- `domain/expectation.py` is not changed.
- Shared Web and control-plane files must be merged after their base feature branches.
- Unrelated Dataset generation and import/export plans must not be included in this
  feature commit.

## 13. Delivery Checkpoints

1. Domain compatibility: purpose, provenance, hashes, and old payload tests.
2. Persistence and service: atomic creation, snapshot copy, draft composition, and
   duplicate rules.
3. API: request validation, error mapping, and JSON compatibility.
4. Web workflow: add dialog, Dataset badges, provenance, publication, and evaluation-page
   refresh.
5. Verification: full Python suite, frontend typecheck/build, and desktop/mobile E2E.

Each checkpoint leaves standard Dataset execution and Single-Case rerun runnable.

## 14. Acceptance Tests

- Old Dataset/Case payloads load without purpose/provenance fields.
- Provenance participates in new hashes without invalidating old hashes.
- Only a completed RunSnapshot Case can be copied.
- New Dataset plus initial draft is atomic.
- Existing active draft and draft-from-published paths both preserve prior members.
- The same source Case is rejected twice in one regression Dataset and allowed in a
  different regression Dataset.
- Unknown and invalid resources map to documented HTTP statuses.
- JSON round trips preserve purpose and provenance.
- Published regression versions execute through the normal RunEngine.
- Publishing, navigating to Evaluation Setup, selecting the new regression Dataset, and
  running it succeeds in desktop and mobile browser tests.
- Standard Dataset and Single-Case rerun tests remain green.

Verification commands:

```bash
PYTHONPATH=src python3 -m pytest -q
cd web
npm run typecheck
npm run build
npm run test:e2e -- --workers=1
```

## 15. Deferred Work

- Case correction, Result Center filters, and confusion-matrix source data:
  future `docs/result/result-center-plan.md` increment.
- Whole-Run regression comparison and controlled variants:
  `docs/experiment/ab-test-plan.md`.
- Automatic regression population and optimization suggestions:
  `docs/optimizer/implementation-plan.md`.
- Queueing, retry, and cancellation:
  `docs/queue/scheduler-adapter-plan.md` and Run lifecycle plan.
- External target write-back:
  external-target and optimizer contracts.
- Excel-specific provenance columns:
  `docs/dataset/import-export-plan.md`.
