# Run Implementation Plan

Last updated: 2026-09-06

## 1. Purpose

The Run capability executes one immutable evaluation request. It connects a published
DatasetVersion to a Target adapter, captures the resulting Trace and Artifacts, invokes
the selected Evaluators, persists Results, and records the final EvaluationRun state.

```text
Run request
    |
    v
RunManifest -> RunEngine -> TargetAdapterProtocol -> Target adapter -> Agent
                    |                                |
                    |                                v
                    +-> Trace -> Evaluators -> EvaluationResults
                    |
                    +-> Artifacts
                    |
                    +-> EvaluationRun state
```

`application/run_management.py` owns the complete user-facing workflow. `run/` owns
only deterministic execution mechanics.

## 2. Final Structure

```text
run/
├── __init__.py
├── target_protocol.py
├── engine.py
├── retry.py
├── process_manager.py
└── artifacts.py
```

Modules are created only when exercised by a real caller. Empty placeholders are not
accepted.

## 3. Terms

- **EvaluationRun**: lifecycle record for one complete evaluation execution.
- **RunManifest**: immutable record of the exact Dataset, Target, Evaluators, metrics,
  gate policy, and effective configuration used by an EvaluationRun.
- **Case execution**: one execution of one Case against the Target.
- **Retry**: a new execution of the same Case after an infrastructure failure.
- **Target**: the Agent or Skill being evaluated.
- **Target adapter**: integration-specific implementation that translates the common
  Target Adapter Protocol into a local Python call, process invocation, or remote HTTP
  API.
- **Trace**: structured behavior history used by Evaluators.
- **Artifact**: file-like output such as stdout, a patch, test report, screenshot, or
  generated file.
- **Job dispatcher**: local/Celery/customer infrastructure that starts a whole Run. It
  is outside `run/`.

There are two distinct asynchronous lifecycles:

```text
Demo Celery or customer scheduler   schedules a complete EvaluationRun
TargetAdapterProtocol               controls one Case execution
```

The demo uses a real job dispatcher under `integrations/job_dispatchers/`. A customer
may replace that dispatcher without changing Engine or the Target Adapter Protocol.

## 4. Ownership Boundaries

`run/` owns:

- consuming an immutable RunManifest constructed from already resolved inputs;
- executing selected Cases;
- invoking a Target through one protocol;
- coordinating Trace collection and evaluation;
- infrastructure-only retries;
- local process mechanics when a local adapter requires them;
- execution Artifact discovery and registration;
- legal Run state changes through domain functions.

`run/` does not own:

- Dataset editing or publication;
- external Target discovery and credentials;
- Agent-specific HTTP, CLI, or SDK behavior;
- evaluator algorithms or evaluator selection policy;
- SQL, HTTP routes, CLI commands, Web pages, queues, or enterprise scheduling;
- observability transport or vendor-specific Trace normalization;
- metric aggregation, reports, or release-gate algorithms.

## 5. Module Contracts

### `target_protocol.py`

Defines the smallest common execution protocol used by `RunEngine`. It contains
execution request/result types only when they are runtime-only and do not belong in the
domain model.

Required behavior:

- `start(request) -> handle` starts one Case execution and returns an opaque string;
- `get_status(handle)` inspects its current status;
- `wait(handle, timeout_seconds)` waits for and returns its normalized result;
- `cancel(handle)` requests cancellation;
- return output, Trace correlation information, and Artifact references without
  exposing vendor response objects to Engine.

The protocol must support both synchronous adapters and adapters backed by remote
asynchronous Agent APIs. Concrete adapters live under `integrations/targets/`.

### `engine.py`

Executes one RunManifest:

1. create and persist a running EvaluationRun;
2. select the Cases pinned by the manifest;
3. execute each Case through `TargetAdapterProtocol`;
4. obtain and normalize the correlated Trace through integration boundaries;
5. reject a Trace that is not eligible for evaluation;
6. invoke the evaluator executor;
7. persist Trace, Results, and Artifact references;
8. transition the EvaluationRun to completed, failed, or cancelled.

Engine does not construct vendor requests, poll observability backends directly,
calculate reports, or act as a scheduler.

### `retry.py`

Applies an explicit retry policy only to classified infrastructure failures such as a
temporary network error, rate limit, process crash, or transient Agent service error.

It never retries wrong answers, policy violations, ordinary evaluator failures, or
release-gate failures. Every retry uses a new execution identity and emits retry
information into the Trace. Coding Agent retries require a fresh Workspace.

Create this module only when Engine has a real retry caller and typed failure
classification.

### `process_manager.py`

Supports local-process Target adapters. It starts and monitors isolated Agent
processes, enforces the configured concurrency limit, maps executions to PIDs and
Workspaces, captures resource usage and exits, and terminates process trees on timeout
or cancellation.

Commands and arguments remain owned by the concrete Target adapter. This module is not
a queue, scheduler, container platform, or persistent worker pool. Create it only with
a real local-process adapter.

### `artifacts.py`

Discovers and registers execution outputs, calculates metadata and hashes, and hands
content to the storage Artifact interface. Domain and database records retain Artifact
references rather than large file bodies.

Create this module only when a Target produces real files or reports that must be
preserved.

## 6. Error And State Rules

- Domain code owns legal `EvaluationRun` state transitions.
- Engine must persist terminal failure state before propagating an execution exception.
- User cancellation is not reported as infrastructure failure.
- Adapter failures cross the protocol as typed, sanitized failures; vendor exceptions
  do not leak into domain objects or API responses.
- Evaluator execution errors become EvaluationResults according to the evaluator
  contract; they do not automatically crash the whole Run.
- Partial persistence must be explicit. A completed Run cannot reference missing
  required Results.
- Credentials, authorization headers, and private Target configuration must never enter
  a RunManifest, Trace, Result, log, or Artifact payload.

## 7. Source Assessment

### `goal/p1-demo`

Preserve:

- published DatasetVersion enforcement;
- creation and persistence of a running EvaluationRun;
- Case-by-Case Target execution;
- Trace and Result persistence;
- terminal completion/failure transitions;
- report behavior only until its caller is moved to the Result/application boundary.

Refactor or reject:

- split the monolithic `run/core.py`;
- remove `LocalScheduler` and `ExternalSchedulerAdapter` from Run;
- reject `PythonFunctionTarget`; the demo receives a specific adapter with a clean
  Agent-native invocation contract;
- replace direct `evaluate_case()` composition with the approved evaluator executor;
- remove hardcoded demo TargetSnapshot construction from Engine;
- remove report construction from Engine.

### `integration/p1-new`

Preserve as behavior references:

- selected-Case execution validation;
- invocation IDs and idempotency keys;
- W3C `traceparent` propagation;
- pending Trace correlation;
- Trace completeness checks;
- timeout diagnostics and exact evaluator/Trace version references on Results.

Do not copy directly:

- obsolete `RunSnapshot`, `Run`, `GateSpec`, repository, and adapter contracts;
- polling and `time.sleep()` embedded directly in Engine;
- vendor/integration errors imported into core execution code;
- old module layout and empty integration scaffolds.

### Current Refactor

Reuse directly:

- `domain.EvaluationRun`, `RunManifest`, `RunStatus`, and `transition_run`;
- current Dataset, Target, Evaluator, Trace, Result, Metric, and Gate contracts;
- `storage.AgentGateRepository` abstractions;
- the approved evaluator executor and observability integration boundaries as they are
  implemented.

### From Scratch

- the minimal Target Adapter Protocol compatible with current domain contracts;
- the decomposed Engine orchestration;
- typed runtime failures and focused contract tests;
- optional retry, process, and Artifact modules only after a real caller is approved.

Reuse means preserving validated behavior after reviewing it against current contracts.
It does not mean copying old code.

## 8. File Migration Map

| Current file | Action | Destination |
| --- | --- | --- |
| `run/core.py` | Split and remove | `run/engine.py`, `run/target_protocol.py`, `integrations/targets/demo_loan.py` |
| empty `run/engine.py` | Implement | `run/engine.py` |
| empty `run/snapshot.py` | Remove | `domain.RunManifest` already owns the complete contract |
| empty `run/lifecycle.py` | Remove | Domain state transitions already own this behavior |
| empty `run/models.py` | Remove | Domain and runtime protocol types own the required models |
| empty `run/scheduler.py` | Remove | `integrations/job_dispatchers/` and application own dispatch |
| empty `run/targets/` | Remove | Concrete adapters belong in `integrations/targets/` |
| empty `run/external/` | Remove | Vendor integrations belong in `integrations/` |
| none | Add when exercised | `run/retry.py`, `run/process_manager.py`, `run/artifacts.py` |

No compatibility aliases from old Run modules are retained.

## 9. Implementation Sequence

Each file requires a source assessment and explicit approval before implementation.

1. Confirm this Run plan and current end-to-end baseline.
2. [complete] Review and implement `run/target_protocol.py`.
3. [complete] Reject redundant `run/manifest.py` and remove empty `run/snapshot.py`.
4. [complete] Review and implement `run/engine.py` with one synchronous execution
   path.
5. Review and implement the demo adapter in `integrations/targets/demo_loan.py` after
   Trace capture and the clean Loan Agent invocation contract are implemented.
6. Migrate `application/run_management.py` or the current application caller to the
   new Engine boundary.
7. Add `retry.py` only after typed infrastructure failures have a real caller.
8. Add `process_manager.py` only with a real local-process Target adapter.
9. Add `artifacts.py` only with a real Artifact-producing Target.
10. Remove `run/core.py`, empty legacy files, old target/external folders, and stale
    imports.
11. Run focused tests, the complete backend suite, and the real demo Run.

## 10. Test Plan

### Protocol

- synchronous Target completion returns normalized execution output;
- asynchronous status/wait/cancel semantics are deterministic;
- timeout, cancellation, and adapter failure remain distinguishable;
- vendor response and credential data cannot cross the protocol.

### Manifest

- only published DatasetVersions are accepted;
- exact Target and Evaluator versions/hashes are retained;
- selected Case IDs are unique and exist in the pinned DatasetVersion;
- content hash is stable for equal effective inputs;
- construction has no persistence or integration side effects.

### Engine

- a complete Dataset executes every selected Case once;
- multi-turn Case input remains ordered;
- Trace correlation and eligibility are enforced before evaluation;
- Results retain exact Run, Case, Evaluator, and Trace references;
- completion, failure, and cancellation persist legal terminal states;
- evaluator errors do not become infrastructure retries;
- rerunning the same manifest does not reuse execution identity.

### Optional Mechanics

- retry accepts only typed retryable failures and creates a fresh execution identity;
- local process timeout terminates the complete process tree;
- concurrency never exceeds the configured limit;
- Artifact hashes and metadata are deterministic and large content stays outside the
  relational record.

## 11. Dependency Rules

```text
domain <- run <- application
          |
          +-> evaluator protocol/executor
          +-> storage repository interface

run/target_protocol.py <- integrations/targets/
application/run_management.py <- integrations/job_dispatchers/
trace/ <- integrations/observability/
```

`run/` must not import FastAPI, Celery, SQL implementations, Web code, or concrete
vendor adapters. Concrete integrations may depend on Run protocols; Run must not depend
on them.

## 12. Completion Gate

Run refactoring is complete when:

- `run/core.py` and all empty legacy Run scaffolds are gone;
- Engine depends on one approved Target Adapter Protocol;
- `domain.RunManifest` owns manifest invariants and hashing, while the application layer
  constructs it from exact resolved assets;
- demo execution preserves P1 behavior through the new boundaries;
- Traces and Results retain exact reproducibility references;
- application code, not Engine, owns the complete user workflow and report retrieval;
- optional modules exist only where exercised;
- focused tests, the complete backend suite, and a real demo Run pass.

## 13. Implementation Decisions

### `run/target_protocol.py`

Status: implemented; 218 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve synchronous execution behavior behind the new lifecycle protocol. |
| `goal/p1-demo` | Reuse none of `Target`, `LocalScheduler`, or `ExternalSchedulerAdapter`; they are forwarding abstractions with mixed ownership. |
| `integration/p1-new` | Adapt request/result correlation, W3C Trace context, adapter identity, and typed failure categories. |
| `integration/p1-new` | Reject obsolete Domain execution models and the credential resolver; credentials belong to concrete integrations. |
| Current refactor | Reuse `Case`, `TargetSnapshot`, `Trace`, and shared validation helpers. |
| From scratch | Implement `CaseExecutionStatus`, immutable request/result records, `TargetExecutionError`, and `TargetAdapterProtocol`. |

### `run/manifest.py`

Status: rejected as redundant

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve RunManifest construction behavior, but move hardcoded demo composition out of Engine. |
| `integration/p1-new` | Reject the obsolete RunSnapshot model; selected-Case execution may be reconsidered only with a real requirement. |
| Current refactor | Reuse `domain.RunManifest` directly; it already owns immutability, validation, exact references, execution limits, and hashing. |
| From scratch | No code justified. A builder would only forward arguments to the Domain constructor. |
| Removed | Empty `run/snapshot.py`; no replacement module and no compatibility alias. |

### `run/engine.py`

Status: implemented; 225 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve sequential Case execution, Trace/Result persistence, and terminal Run transitions. |
| `goal/p1-demo` | Remove manifest construction, report building, scheduler forwarding, and hardcoded demo Target details from Engine. |
| `integration/p1-new` | Adapt execution identity, Trace context, strict Trace identity checks, and timeout cancellation. |
| `integration/p1-new` | Reject direct polling, obsolete models, and concrete integration exceptions in Engine. |
| Current refactor | Reuse `EvaluationRun`, `transition_run`, repository operations, and `TargetAdapterProtocol`. |
| From scratch | Inject Case evaluation and Trace resolution, validate complete Result sets, and fail closed for unimplemented retry/parallel settings. |

### `integrations/targets/demo_loan.py`

Status: implemented; application caller migration pending

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve Case-by-Case deterministic demo behavior; reject `PythonFunctionTarget` and Agent-side Case iteration. |
| `integration/p1-new` | Preserve W3C Trace context propagation only; reject old execution models and polling. |
| Current refactor | Reuse `TargetAdapterProtocol`, `LoanAgent.invoke()`, and in-memory Trace capture. |
| From scratch | Implement synchronous lifecycle state, Case-to-turn translation, completion spans, and typed adapter errors. |
