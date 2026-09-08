# Application Implementation Plan

Last updated: 2026-09-08

## 1. Purpose

The Application layer exposes complete AgentGate use cases to FastAPI, CLI commands,
background workers, and external control planes. It resolves exact versions, coordinates
core capabilities, and persists their outputs.

It is not a second Domain layer and not an enterprise Control Plane.

```text
Transport or worker request
          |
          v
Application use case
  -> resolve immutable inputs
  -> invoke one core capability
  -> coordinate persistence
  -> return domain objects or application read models
```

## 2. Final Structure

```text
application/
├── run_management.py
├── dataset_management.py
├── dataset_generation.py      future
├── target_catalog.py
├── evaluator_management.py
├── result_reader.py
├── skill_analysis.py
└── lineage_queries.py
```

Files are added only when a real caller exercises them. Empty placeholders are not
created.

## 3. Ownership Rules

Application modules own:

- complete user and worker use cases;
- exact version resolution before immutable snapshots are created;
- composition of core capabilities and integration adapters;
- transaction and persistence coordination through repository contracts;
- application-level not-found, conflict, and precondition decisions;
- read models needed by more than one transport.

Application modules do not own:

- HTTP routes, request schemas, CLI formatting, or Celery tasks;
- Domain models or invariants;
- Agent execution mechanics, evaluator algorithms, result formulas, or SQL;
- vendor protocols, credentials, OTel transport, or UI presentation labels;
- a generic service locator or dependency-injection framework.

## 4. Module Contracts

### `run_management.py`

Owns Run creation, submission, cancellation, and the shared worker-side execution entry
point.

- Resolves a published Dataset version and selected Evaluator versions.
- Accepts an exact `TargetSnapshot`; Target discovery belongs in `target_catalog.py`.
- Constructs and persists a pending `EvaluationRun` with an immutable `RunManifest`.
- Invokes `RunEngine` with a concrete Target adapter and Trace resolver.
- Keeps submission separate from execution so local code, Celery, and customer
  schedulers call the same worker boundary.
- Does not execute Cases itself, build reports, or implement a queue.

P1 public operations:

```text
create_run(...)      -> persisted pending EvaluationRun
dispatch_run(...)    -> submit only run_id or persist a safe dispatch failure
execute_run(...)     -> completed/failed/cancelled EvaluationRun
fail_stale_runs(...) -> fail abandoned running Runs after their recovery deadline
```

Add running-Run cancellation only when execution handles are persisted and a real
dispatcher can route cancellation to the active worker. Do not claim cancellation that
the synchronous POC cannot perform.

### `dataset_management.py`

Owns user-facing Dataset and Case lifecycle workflows: create, update, archive, draft,
publish, import, export, copy, reorder, and Case editing.

It delegates immutable mechanics to `dataset/`, invariants to `domain/`, and persistence
to `storage/`. It does not execute or generate Cases.

### `dataset_generation.py`

Future workflow for generating a Dataset draft from an exact Target descriptor. It
coordinates `target_catalog.py`, generation algorithms, a model provider, and Dataset
management. Implement only after generation requirements and a real caller are approved.

### `target_catalog.py`

Owns read-only Target discovery and exact version resolution across external platforms.
It returns normalized `TargetDescriptor` and `TargetSnapshot` objects and selects the
configured platform adapter.

It does not edit customer Agents, invoke a Target, store plaintext credentials, or
silently resolve mutable `latest` aliases for execution.

### `evaluator_management.py`

Owns AgentGate-managed Evaluator definitions and immutable versions: create, validate,
publish, disable, list, and exact-version resolution.

It explicitly maps supported evaluator definitions to implementations. It does not add a
dynamic plugin registry, execute evaluations, or calculate aggregate metrics.

### `result_reader.py`

Owns read-only Run output workflows shared by Web, CLI, and API:

- complete Evaluation reports;
- Case Results and Badcases;
- Trace and Artifact details;
- dashboard counts, recent Runs, and latest summary data.

It delegates report construction to `result/report.py`. It does not calculate evaluator
scores, update Cases, or render presentation labels.

### `skill_analysis.py`

Future workflow for static Skill conflict, confusion, and Prompt-alignment analysis. It
resolves an exact Target descriptor, invokes the analysis pipeline, and persists immutable
reports and separate human reviews.

### `lineage_queries.py`

Owns read-only questions over immutable RunManifest references, such as which Runs used a
specific Dataset, Target, or Evaluator version. It does not write a separate lineage
graph. Add a graph capability only when multi-hop analysis has a real requirement.

## 5. Main Call Chains

### Synchronous POC

```text
FastAPI / CLI
  -> RunManagement.create_run()
  -> RunManagement.execute_run()
  -> RunEngine
  -> Target adapter + Trace resolver
  -> Evaluators
  -> ResultReader
```

### Background Or Customer-Controlled Execution

```text
FastAPI / customer control plane
  -> RunManagement.create_run()
  -> dispatcher submits run_id
  -> worker calls RunManagement.execute_run(run_id, adapter, resolver)
  -> status and results remain authoritative in AgentGate storage
```

Celery or a customer scheduler transports the `run_id`; it does not duplicate
RunManifest, Trace, Result, or gate state.

## 6. Source Assessment

### `goal/p1-demo`

Preserve:

- Dataset and Evaluator selection;
- demo bootstrap and synchronous launch behavior;
- overview, report, Trace, version, Dataset, and Evaluator read behavior until moved;
- shared use by CLI and FastAPI.

Refactor or reject:

- split broad `control_plane/EvaluationService` by business capability;
- remove manifest construction and report building from the old Run Engine;
- remove direct construction of the old Case-aware Loan Agent;
- remove Chinese presentation labels from backend application responses;
- remove the `control_plane/` package after callers migrate.

### `integration/p1-new`

Use only as design references:

- exact Target version registration;
- external Target resolution;
- selected evaluator validation;
- rerun and regression workflow requirements.

Reject:

- obsolete RunSnapshot, Target, repository, and adapter contracts;
- the large mutable in-memory Target registry as a final architecture;
- fallback behavior that hides Target-catalog failures;
- vendor exceptions and polling inside application workflows;
- combining Run, regression editing, comparison, JSON Schema validation, target
  registration, and read APIs in one service.

### Current Refactor

Reuse:

- `DatasetManagement`;
- immutable Domain models and Run transitions;
- `RunEngine`, `TargetAdapterProtocol`, and Trace resolver boundary;
- Evaluator validation/execution and Result report construction;
- `AgentGateRepository`.

### From Scratch

- capability-oriented application APIs;
- exact Run creation and worker execution composition;
- Result read models where direct Domain objects are insufficient;
- focused tests at use-case boundaries.

Reuse means preserving validated behavior under current contracts, not copying old
modules.

## 7. Migration Map

| Current owner | Behavior | Destination |
| --- | --- | --- |
| `control_plane/service.py` | launch/create/execute Run | `application/run_management.py` |
| `control_plane/service.py` | report, overview, Trace reads | `application/result_reader.py` |
| `control_plane/service.py` | Dataset summaries | `application/dataset_management.py` or transport mapping |
| `control_plane/service.py` | Evaluator listing | `application/evaluator_management.py` |
| `control_plane/service.py` | Target versions | `application/target_catalog.py` |
| `control_plane/service.py` | regression Case editing | `application/dataset_management.py` |
| `control_plane/service.py` | rerun orchestration | `application/run_management.py` |
| `control_plane/service.py` | rerun comparison | `result/comparison.py` through `result_reader.py` |
| `control_plane/service.py` | JSON Schema validation | `application/evaluator_management.py` |
| `run/core.py` | manifest and Run creation | `application/run_management.py` |
| `run/core.py` | report retrieval | `application/result_reader.py` |

No compatibility facade remains after Server and CLI imports migrate.

## 8. Error And Security Rules

- Application errors identify the failed use case without exposing credentials or vendor
  payloads.
- Unknown IDs and unavailable exact versions fail explicitly.
- Published immutable versions are required for execution.
- A pending Run is persisted before dispatch or execution.
- Worker execution reloads the persisted Run; callers cannot replace its manifest.
- Plaintext credentials never enter application read models, RunManifest, logs, or
  dispatcher payloads.
- External callbacks and retries must be idempotent by Run or execution identity.
- Application code does not catch broad exceptions merely to continue with fallback
  configuration.

## 9. Implementation Sequence

Each file requires source assessment and explicit approval before implementation.

1. [complete] Implement `dataset_management.py`.
2. [complete] Implement the initial `run_management.py` create/execute boundary.
3. [complete] Implement the initial `result_reader.py` and move report, Trace, and
   overview reads.
4. [complete] Migrate demo composition to the new Run management boundary.
5. [complete] Update FastAPI and CLI imports to use capability-oriented application
   modules.
6. [complete] Remove `control_plane/`, `run/core.py`, old Python Target tests, and empty
   legacy Run scaffolds.
7. Implement `target_catalog.py` when external Target discovery begins.
8. Implement `evaluator_management.py` when Evaluator CRUD/version APIs begin.
9. Implement `lineage_queries.py` using persisted RunManifest indexes.
10. Implement generation and Skill-analysis workflows only with their first real callers.

## 10. Test Plan

### Run Management

- exact published Dataset and selected Evaluators are pinned;
- pending Run is persisted before execution;
- duplicate/unknown Evaluators and unknown Runs fail;
- worker execution reloads immutable persisted inputs;
- adapter and Trace identity mismatches fail closed;
- fixed and risky demo versions preserve expected gate behavior.

### Result Reader

- only completed Runs produce normal reports;
- missing Results produce fail-closed gates;
- overview counts are derived from authoritative persisted data;
- Trace lookup cannot cross Run/Case identity;
- returned read data contains no credential material.

### Regression

- FastAPI and CLI use the same application workflows;
- current Dataset editing remains unchanged;
- all backend tests pass;
- one end-to-end demo Run uses real OTel spans and the new Run Engine;
- no imports remain from `control_plane` or `run.core` after migration.

## 11. Coding Rules

- Prefer small capability classes with explicit constructor dependencies.
- Use plain functions for stateless transformations.
- Do not add base service classes, inheritance hierarchies, service locators, or generic
  repository wrappers.
- Keep read and write workflows separate when they have different dependencies.
- Pass IDs across dispatcher boundaries and reload authoritative state.
- Keep transport dictionaries at transport boundaries; use typed Domain objects inside.
- Add an abstraction only when at least two real callers require the same behavior.
- Do not retain compatibility aliases during the refactor.

## 12. Completion Gate

Application refactoring is complete when:

- every Server, CLI, worker, and external-control-plane entry point calls an Application
  use case;
- `control_plane/` and the old `run/core.py` are removed;
- Run creation and worker execution share one immutable boundary;
- reports and overview reads are outside Run execution code;
- no application module owns vendor protocols, SQL, or evaluator algorithms;
- fixed/risky and multi-turn demonstrations preserve expected behavior;
- the complete backend suite and end-to-end demo pass.

## 13. Implementation Decisions

### `application/run_management.py`

Status: create, execute, dispatch, stale-Run, FastAPI, and Celery worker workflows
implemented

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve Dataset/Evaluator selection, immutable Run creation, persistence, and synchronous execution behavior. |
| `integration/p1-new` | Preserve exact Target snapshot and selected-evaluator ideas; reject obsolete models and the broad registry/service. |
| Current refactor | Reuse `DatasetManagement`, `RunManifest`, `RunEngine`, evaluator validation/execution, and repository contracts. |
| From scratch | Implement separate `create_run()` and `execute_run()` operations so dispatchers transport only `run_id`. |

### `application/result_reader.py`

Status: activity, progress, exact status counts, reports, and Trace reads implemented

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve Run listing, report, Trace, and overview reads; separate them from execution. |
| `integration/p1-new` | Reject the broad service and obsolete read models. |
| Current refactor | Reuse repository contracts and `result/report.py`. |
| From scratch | Implement strict Run/Trace lookup, completed-Run report checks, and status-aware overview data. |

`ResultReader.overview()` and Run activity use exact repository status counts rather
than the bounded history page. Progress is derived from complete per-Case evaluator
result sets, and pending queue position tolerates concurrent worker claims.
