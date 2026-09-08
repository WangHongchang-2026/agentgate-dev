# Controlled A/B Run Comparison

Status: implemented on `feature/ab-testing` for the POC.

## Scope

AgentGate can create a controlled baseline/candidate pair of ordinary Evaluation Runs and
compare their completed reports through the existing Run comparison capability.

For this POC:

- the Dataset version, ordered Cases, Evaluators, metric plan, release gate, and execution
  settings are controlled inputs;
- baseline A and candidate B are different immutable versions of the same demo Agent;
- both Runs use the existing Run lifecycle, dispatcher, persistence, status, Result, and
  lineage capabilities;
- the comparison remains a pure calculation over two compatible completed reports.

This is controlled A/B Run-pair creation and comparison. It is not complete A/B
management.

## Customer Workflow

1. The client selects baseline and candidate demo Agent version IDs.
2. The client selects one published Dataset version and optional Evaluators.
3. `POST /api/run-comparisons` creates and dispatches two controlled Runs.
4. The response returns the baseline and candidate Run IDs and current statuses.
5. The client uses the ordinary Run endpoints to monitor both Runs.
6. After both Runs complete, the client calls `GET /api/run-comparisons` with both IDs.

The client must retain both Run IDs. AgentGate does not assign a third experiment or pair
identity.

## Source Assessment

### `goal/p1-demo`

The old `experiment/` package contained docstring-only assignment, model, comparison,
statistics, and service placeholders. Its `result/compare.py` boundary was also empty.
Those files supplied no behavior worth copying and the rejected generic experiment
package was not restored.

### `integration/backend-features`

The feature branch was updated through integration commit `9686d59`, including Skill
Analysis. A/B work reuses the integrated capabilities without changing their ownership:

- `RunManagement` resolves immutable evaluation inputs and persists ordinary Runs;
- `JobDispatcher` submits persisted Run IDs;
- `TargetCatalog` resolves exact demo Target descriptors;
- `ResultReader.compare_runs(...)` loads completed reports;
- `result/comparison.py` validates compatibility and calculates deterministic deltas;
- the existing GET comparison API returns those deltas.

### Current refactor

The controlled pair orchestration was written from scratch in
`application/ab_testing.py`. It composes the existing boundaries rather than copying the
old scaffolds or introducing an experiment subsystem.

## Architecture And Ownership

```text
POST /api/run-comparisons
        |
        v
ServerDependencies.submit_ab_runs(...)
        |
        v
application.create_ab_runs(...)
        |
        +--> RunManagement.create_run(A)
        +--> RunManagement.create_run(B)
        +--> JobDispatcher.submit(A run_id)
        +--> JobDispatcher.submit(B run_id)

GET /api/run-comparisons?baseline_run_id=...&candidate_run_id=...
        |
        v
ResultReader.compare_runs(...)
        |
        v
result.compare_reports(...)
```

Ownership remains narrow:

- `application/ab_testing.py` validates the controlled pair and coordinates creation and
  dispatch;
- `server/dependencies.py` resolves canonical demo Target versions and calls the
  application function;
- `server/routes/comparisons.py` owns HTTP request/response models and error mapping;
- `result/comparison.py` remains the unchanged general comparison algorithm;
- `EvaluationRun` remains the only persisted lifecycle record involved.

## Controlled-Variable Invariants

The baseline and candidate must:

- be Agent Targets;
- use the same `source_id` and `external_target_id`;
- use different `external_version_id` values;
- use different immutable Target snapshots;
- use distinct Evaluation Run IDs;
- use the same Dataset version, content hash, and ordered Case identities;
- use identical Evaluator IDs, versions, and content hashes;
- use identical primary Evaluators, metric plan, release gate, timeout, retry limit, and
  Case parallelism.

Both Target descriptors are resolved before either Run is created. Shared Dataset and
Evaluator validation continues to belong to `RunManagement`.

## Application Workflow

`create_ab_runs(...)` accepts `RunManagement`, `JobDispatcher`, two resolved Target
snapshots, and one shared evaluation configuration. It creates both Runs before dispatching
either one. Dispatch is attempted independently for baseline and candidate.

`ABRunPair` is an immutable application response model that contains the two current
`EvaluationRun` values and enforces the controlled-pair invariants. It is returned only
within the process and is not stored.

If one dispatch fails, existing Run behavior records that Run as failed without persisting
credential-bearing exception text. Dispatch of the other Run is still attempted, and the
returned pair exposes the resulting failed/pending statuses.

## POST Contract

`POST /api/run-comparisons` returns `202 Accepted`.

Request:

```json
{
  "baseline_version": "loan-agent-v1-risky",
  "candidate_version": "loan-agent-v2-fixed",
  "dataset_id": "loan-risk-policy",
  "dataset_version": 1,
  "evaluator_ids": ["skill-routing", "final-state"]
}
```

Only canonical demo version IDs and shared evaluation selections are accepted. Extra
fields are forbidden, so the browser cannot submit raw Target snapshots, adapter settings,
invocation configuration, or credentials.

Response:

```json
{
  "baseline": {
    "run_id": "baseline-run-id",
    "status": "pending"
  },
  "candidate": {
    "run_id": "candidate-run-id",
    "status": "pending"
  }
}
```

The response intentionally contains no full Run manifest or A/B identity.

Invalid versions, incompatible variants, and invalid Dataset or Evaluator selections
return a sanitized `422`. An unexpected dispatch infrastructure failure that cannot be
represented by persisted Run states returns a sanitized `503`.

## GET Contract

The existing read endpoint is unchanged:

```text
GET /api/run-comparisons
    ?baseline_run_id=<baseline-run-id>
    &candidate_run_id=<candidate-run-id>
```

Both Runs must be completed and compatible. Unknown Runs return `404`; incomplete or
incompatible Runs return `409`.

The response includes gate, metric, overall-score, and Case-level deltas from the existing
`EvaluationComparison` contract.

## Persistence And Lifecycle Boundaries

AgentGate persists two ordinary Evaluation Runs. It does not persist:

- `ABRunPair`;
- an A/B Test or experiment identity;
- membership linking the two Runs after the response;
- A/B history;
- an experiment lifecycle;
- an A/B lineage node or edge.

Each Run retains its normal independent lineage. Later comparison is reconstructed by
supplying both Run IDs.

## Implemented Files

```text
src/agentgate/
├── application/
│   ├── __init__.py
│   └── ab_testing.py
└── server/
    ├── dependencies.py
    └── routes/
        └── comparisons.py

tests/
├── test_ab_testing.py
└── test_result_comparison_api.py
```

No storage table, repository method, domain entity, scheduler, CLI command, Web page,
statistics module, or experiment package was added.

## Verification

Focused coverage verifies:

- controlled pair creation and persistence;
- descriptor preflight before Run creation;
- rejection of identical versions and different logical Agents;
- independent dispatch and partial dispatch failure;
- immutable pair invariants;
- compact `202` response shape;
- rejection of unknown demo versions and raw Target configuration;
- preservation of the existing GET comparison behavior.

The full backend regression passes with `640 passed` and one existing Starlette TestClient
deprecation warning.

## Deferred Capabilities

The following require separate customer requirements and design checkpoints:

- persisted A/B history and experiment identity;
- A/B-specific lineage;
- statistical significance and confidence;
- automatic winner selection;
- latency comparison based on explicit Case or Trace timing evidence;
- non-demo Target selection;
- recurring experiments or traffic assignment;
- A/B CLI and Web workflows.
