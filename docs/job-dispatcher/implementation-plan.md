# Job Dispatcher Implementation Plan

Last updated: 2026-09-07

## 1. Purpose

The Job Dispatcher capability runs an already-persisted `EvaluationRun` outside the
FastAPI request process. The POC uses Celery with Redis so the Web application can
show queued and running work while a separate worker executes the evaluation.

```text
Web
 |
 | POST /api/evaluations
 v
FastAPI -> create PENDING EvaluationRun in SQLite
              |
              v
       JobDispatcher.submit(run_id)
              |
              v
        Redis broker -> Celery worker
                            |
                            v
                    RunManagement.execute_run(run_id)
                            |
                            v
                        RunEngine
```

SQLite is the source of truth for Run status, progress, timestamps, errors, and
results. Redis and Celery are operational delivery infrastructure only.

## 2. Final Structure

```text
integrations/
└── job_dispatchers/
    ├── __init__.py
    ├── protocol.py
    └── celery.py
```

Related existing modules will be modified rather than duplicated:

```text
application/run_management.py
application/result_reader.py
run/engine.py
storage/repository.py
storage/sqlite.py
server/dependencies.py
server/routes/runs.py
web/src/...
```

There is no top-level `queue/` package. There is no duplicate Task, Job, TaskRun, or
CaseExecution domain model in P1.

## 3. Terms

- **EvaluationRun**: authoritative lifecycle record for one complete evaluation.
- **Dispatcher**: submits the ID of an existing Run for asynchronous execution.
- **Worker**: receives a `run_id`, reconstructs runtime dependencies, and calls the
  shared application service.
- **Broker**: Redis transport used by Celery to deliver work.
- **Queue position**: best-effort submission order derived from pending Runs in
  SQLite. It is not an exact Redis broker position.
- **Scheduler**: chooses when a Run should be submitted, such as a customer Java
  scheduler or a future reservation feature. Immediate POC dispatch is not scheduling.
- **Progress**: number of fully evaluated Cases divided by the number of Cases pinned
  in the RunManifest.

Celery Beat is not required. The POC dispatches Runs immediately after creation.

## 4. Ownership Boundaries

The job-dispatcher integration owns:

- submitting only a `run_id` to Celery;
- declaring the Celery task and Redis broker configuration;
- reconstructing process-local dependencies in the worker;
- invoking `RunManagement.execute_run(run_id, ...)`;
- broker delivery options and operational logging.

It does not own:

- Run state or legal state transitions;
- Dataset, Target, or Evaluator snapshots;
- Case execution or evaluation logic;
- progress and metric calculation;
- durable result storage;
- Web/API response models;
- time-based scheduling or enterprise Control Plane behavior.

The same application execution boundary must support a future customer scheduler:

```text
Customer scheduler -> AgentGate HTTP start endpoint -> persisted Run -> dispatcher

or

Customer worker integration -> RunManagement.execute_run(run_id)
```

Customer integration changes the dispatch adapter, not `RunEngine`.

## 5. Dispatcher Contract

`protocol.py` defines one small structural protocol:

```python
class JobDispatcher(Protocol):
    def submit(self, run_id: str) -> None: ...
```

Rules:

- the Run must already exist before `submit()` is called;
- the payload contains only the non-blank `run_id`;
- Dataset content, credentials, prompts, and snapshots never enter the broker message;
- Celery uses `run_id` as the task ID where practical for operational correlation;
- application code depends on the protocol, not Celery;
- tests use a small in-test fake; no production `inline.py` is added unless a real
  non-Celery runtime needs it.

## 6. Run State And Delivery Rules

### Authoritative state

The existing `RunStatus` values remain unchanged:

```text
PENDING    displayed as Queued
RUNNING    displayed as Running
COMPLETED  displayed as Completed
FAILED     displayed as Failed
CANCELLED  displayed as Cancelled
```

FastAPI creates and persists the `PENDING` Run before dispatch. The worker changes it
to `RUNNING`; `RunEngine` persists the terminal state.

Celery task states are not returned to the Web and are not used to reconstruct
business history.

### Duplicate delivery

Celery tasks may be delivered more than once. Starting a Run must therefore be an
atomic claim, not a read followed by an ordinary save.

Add one repository operation with compare-and-set semantics:

```python
claim_pending_run(run_id: str, started_at: datetime) -> EvaluationRun | None
```

SQLite updates the row only when its current status is `PENDING`. One worker receives
the claimed Run; another delivery receives `None` and exits without invoking the
Target. No `Attempt` domain class is introduced.

### Worker failure

Celery late acknowledgment may redeliver a task, so the task must remain idempotent.
However, a worker can die after changing the Run to `RUNNING`. P1 does not resume a
partially executed Run.

Add stale-Run reconciliation at application startup and before activity queries:

- identify `RUNNING` Runs older than `manifest.timeout_seconds + grace_seconds`;
- transition them to `FAILED` with a sanitized stale-worker error;
- retain already-persisted traces and evaluation results for debugging;
- never silently reset a stale Run to `PENDING`.

Celery configuration uses late acknowledgment only after the atomic claim exists.
`task_reject_on_worker_lost` remains disabled in P1 to avoid uncontrolled message
loops.

## 7. Progress Model

Do not add a mutable progress counter or a CaseExecution domain class.

```text
total_cases     = number of Cases in RunManifest.dataset
completed_cases = Cases having the complete selected Evaluator result set
progress        = completed_cases / total_cases
```

`RunEngine` currently saves all Results at the end. It will instead persist each
Case's complete result set immediately after that Case has been evaluated. This gives
durable progress and preserves useful evidence if a later Case fails.

Progress is derived from Results rather than Traces because a saved Trace only proves
that Target execution finished; evaluation may still be running or may fail.

## 8. Read Models And API

`ResultReader` exposes application read models for Run activity. Storage queries must
not use the existing default 50-Run limit when calculating global status counts.

Required projections:

- status counts;
- queued Runs ordered by `created_at`, oldest first;
- running Runs;
- recent terminal Run history;
- per-Run progress, timestamps, duration, and sanitized error;
- best-effort queue position for pending Runs.

Required API behavior:

```text
POST /api/evaluations
  Persist PENDING Run, submit run_id, return 202 Accepted.

GET /api/runs
  Return filterable Run history.

GET /api/runs/activity
  Return status counts and queued/running/recent projections.

GET /api/runs/{run_id}/status
  Return lifecycle state, progress, timestamps, duration, error, and queue position.

GET /api/runs/{run_id}
  Keep the existing completed-report behavior.
```

If broker submission fails after Run creation, FastAPI transitions the Run to
`FAILED` with a sanitized dispatch error and returns a service-unavailable response.

## 9. Web Behavior

The Web application reads only AgentGate APIs. It does not call Redis, Celery, or
Flower.

Required POC visualization:

- Overview counters for queued, running, completed, failed, and cancelled Runs;
- a Run workspace with queued, running, and history filters;
- stable progress bars showing completed and total Cases;
- submission time, start time, duration, and failure reason;
- best-effort queue position where available;
- automatic polling every two seconds while queued or running work exists;
- stop unnecessary polling when no active Runs remain.

Visible UI labels are Chinese. Source identifiers, API fields, TypeScript names, and
comments remain English.

P1 cancellation is intentionally limited:

- pending cancellation may be added using an atomic SQLite transition and Celery
  revoke;
- active cancellation is deferred until `RunEngine` and Target adapters support
  cooperative cancellation;
- the server must not programmatically terminate a Celery worker process.

## 10. Celery Configuration

P1 uses Redis only as the Celery broker. A Celery result backend is unnecessary
because durable state is stored in SQLite.

Initial settings:

- JSON task serialization;
- accepted content restricted to JSON;
- one task argument: `run_id`;
- worker concurrency `1` by default for the small demo host;
- task time limit greater than the maximum Run timeout plus cleanup allowance;
- late acknowledgment enabled only with atomic Run claiming;
- worker-lost rejection disabled;
- task result storage disabled.

Secrets and Redis URLs come from environment configuration and are never stored in a
RunManifest or returned by an API.

## 11. Source Assessment

### `goal/p1-demo`

Reuse as reviewed behavior:

- `EvaluationRun` lifecycle and SQLite persistence;
- `RunManagement.create_run()` and `execute_run()` separation;
- `RunEngine` Case loop and terminal-state handling;
- Web status concepts already present in the POC.

Refactor:

- replace request-process execution with create-then-dispatch;
- persist each Case's Results during execution;
- add atomic Run claiming and uncapped activity queries.

Reject:

- `LocalScheduler` and `ExternalSchedulerAdapter` that schedule individual Cases;
- any scheduler dependency inside `RunEngine`.

### `integration/p1-new`

Reuse only as behavior and UI references:

- queued/running/terminal status displays;
- total/completed/passed Case counts;
- submission, start, and completion timestamps;
- task-list filtering and progress presentation.

Do not copy directly:

- duplicate Task, EvalTask, TaskRun, CaseExecution, Agent, or Evaluator models;
- global mutable service registration;
- the placeholder top-level `queue/` package;
- empty `run/scheduler.py` scaffolding;
- application and storage concerns mixed into scheduling code.

### Current refactor

Reuse directly:

- Domain `EvaluationRun`, `RunManifest`, `RunStatus`, and legal transitions;
- application `RunManagement` and `ResultReader` boundaries;
- `RunEngine` and Target Adapter Protocol;
- SQLite repositories;
- modular FastAPI routes and dependencies;
- existing Web API client and Run views where their contracts remain useful.

### Write from scratch

- `JobDispatcher` protocol;
- Celery application, task, and dispatcher adapter;
- atomic pending-Run claim;
- stale-Run reconciliation;
- Run activity and progress projections;
- async API contracts and Web polling behavior.

## 12. Implementation Sequence

Goal Mode authorized this sequence for autonomous implementation.

1. [complete] Add `integrations/job_dispatchers/protocol.py` and protocol tests.
2. [complete] Add atomic claim and activity query contracts to `storage/repository.py`.
3. [complete] Implement the contracts transactionally in `storage/sqlite.py`.
4. [complete] Modify `run/engine.py` to claim a Run and persist Results per completed Case.
5. [complete] Modify `application/run_management.py` for dispatch and stale reconciliation.
6. [complete] Extend `application/result_reader.py` with progress and activity projections.
7. [complete] Add `integrations/job_dispatchers/celery.py` and focused Celery task tests.
8. [complete] Change FastAPI dependencies and Run routes to asynchronous submission and
   status reads.
9. [complete] Add Chinese lifecycle counters and queued/running/history views to the Run
   workspace, with polling that stops when no active Runs remain.
10. [complete] Run backend tests, API integration tests, Web checks, and real-stack
    desktop/mobile browser verification.

No compatibility aliases are added during the refactor.

## 13. Verification

Backend behavior:

- creating an evaluation returns `202` with a persisted `PENDING` Run;
- the Celery message contains only `run_id`;
- one of two concurrent claims succeeds and Target execution occurs once;
- a worker completes the Run and persists Case progress incrementally;
- a duplicate delivery is a no-op;
- broker failure produces a durable failed Run;
- stale running work becomes failed without losing partial evidence;
- status counts include all Runs rather than only the latest 50;
- queue order is deterministic for Runs with distinct creation times.

Web behavior:

- Run workspace lifecycle counts update while a Run moves through queued, running,
  and terminal states;
- progress cannot resize or shift the Run row;
- polling starts and stops according to active work;
- errors and timestamps render without overlapping controls;
- desktop and mobile views remain usable.

Operational smoke test:

```text
Start Redis
Start one Celery worker
Start FastAPI
Start the Web application
Submit two Runs
Observe one running and one queued Run
Observe both complete and appear in history
```

## 14. Implementation Outcome

The completed slice reused the current refactor's Domain, RunManagement, RunEngine,
ResultReader, repository, and modular FastAPI boundaries directly. It adapted the
`goal/p1-demo` lifecycle behavior and `integration/p1-new` queue/progress presentation
ideas to the approved single-`EvaluationRun` model. The dispatcher protocol, Celery
adapter/task, atomic claim, stale reconciliation, projections, async API, and Web polling
were written from scratch; no code was blindly copied and no duplicate Task model or
compatibility contract was added.

Verification completed on 2026-09-07:

- `pytest -q`: 289 passed;
- Web typecheck and production build: passed;
- Playwright with real Redis, one Celery worker, FastAPI, SQLite, and Vite: 8 passed
  across desktop and mobile;
- two-Run operational smoke: observed one 300-Case Run running, the second queued at
  position 1, and both subsequently completed in history.

The standalone Web Overview page remains Phase 6 work. The Run workspace owns the five
lifecycle counters required for this dispatcher POC.

## 15. Deferred Capabilities

- time-based reservations and recurring schedules;
- priority queues and tenant fairness;
- multiple worker pools and resource-aware routing;
- exact broker queue position;
- active cooperative cancellation;
- automatic retry or resume of partial Runs;
- high-availability broker and PostgreSQL deployment;
- a customer-specific Java scheduler adapter;
- Flower or another operational Celery dashboard;
- enterprise admission control, quotas, and approval workflows.
