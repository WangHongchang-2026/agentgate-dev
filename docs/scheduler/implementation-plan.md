# Scheduled Run Implementation Plan

Last updated: 2026-09-09

## 1. Purpose

The POC lets a user create an Evaluation Run now and request that it enter the
execution queue at a future UTC time.

```text
FastAPI -> SQLite SCHEDULED Run
                    |
          10-second Celery Beat tick
                    |
                    v
             PENDING Run -> Redis -> Celery worker -> RunEngine
```

SQLite is the durable source of truth. Redis receives only `run_id` after the
requested time arrives. `scheduled_for` is scheduling metadata on `EvaluationRun`;
it is not part of the immutable `RunManifest` because it does not affect evaluation
reproducibility.

## 2. POC Boundary

- one Business Unit and one execution queue;
- one-time future execution only;
- UTC, timezone-aware timestamps;
- configurable scheduler interval, defaulting to 10 seconds;
- query and cancellation through the existing Run APIs;
- fixed Celery worker capacity;
- no recurring schedules, priorities, tenant quotas, queue estimates, or Web work;
- no external customer scheduler adapter.

`scheduled_for` means when a Run becomes eligible to enter the queue. It does not
guarantee that worker capacity is available at that exact time.

## 3. Source Decision

| Source | Decision |
| --- | --- |
| `p1-demo` / current `refactor-1` | Reuse `EvaluationRun`, SQLite storage, atomic state changes, cancellation, Celery dispatch, and Run APIs |
| `integration/p1-new` | No direct code reuse |
| New implementation | Add scheduled lifecycle, due-time claim, scheduling application workflow, periodic Celery dispatch, and focused tests |

Reuse means preserving accepted contracts and adapting them to the refactor style. It
does not mean copying old modules unchanged.

## 4. Code Structure

```text
domain/run.py
application/run_scheduling.py
application/run_management.py
storage/repository.py
storage/sqlite.py
integrations/job_dispatchers/celery.py
server/dependencies.py
server/routes/runs.py
tests/test_run_scheduling.py
```

No top-level scheduler package or duplicate Job domain model is introduced.

## 5. Lifecycle

```text
SCHEDULED -> PENDING -> RUNNING -> COMPLETED
     |           |          |
     +-----------+----------+-> CANCELLED
                 |
                 +------------> FAILED
```

Rules:

- `SCHEDULED` requires `scheduled_for > created_at`;
- a scheduled Run has no execution timestamps or outcome;
- release before `scheduled_for` is rejected;
- due Runs are atomically changed from `SCHEDULED` to `PENDING`;
- duplicate scheduler ticks cannot claim the same Run twice;
- cancellation of `SCHEDULED` changes SQLite state without revoking a nonexistent
  broker task;
- dispatch errors are stored as sanitized Run failures.

## 6. Scheduler And Workers

Celery Beat publishes `agentgate.dispatch_due_evaluation_runs` every 10 seconds to a
small dedicated `agentgate.scheduler` queue. A scheduler worker consumes that queue,
claims due SQLite Runs, and submits their IDs to the normal Celery execution queue.

```text
celery beat
    |
    v
scheduler worker (`agentgate.scheduler`)
    |
    v
execution worker (default queue)
```

Keeping the scheduler tick off the execution queue prevents a long evaluation from
delaying schedule release when execution-worker concurrency is one.

Configuration:

```text
AGENTGATE_SCHEDULER_INTERVAL_SECONDS=10
AGENTGATE_WORKER_CONCURRENCY=1
```

## 7. API

`POST /api/evaluations` accepts optional `scheduled_for`.

- omitted: persist `PENDING`, then dispatch immediately;
- future UTC timestamp: persist `SCHEDULED`, do not dispatch immediately;
- invalid, naive, or non-future timestamp: reject the request.

Existing APIs remain responsible for reading and cancellation:

```text
GET  /api/runs?status=scheduled
GET  /api/runs/{run_id}/status
GET  /api/runs/activity
POST /api/runs/{run_id}/cancel
```

## 8. Deferred Production Work

- Business Unit identity, RBAC, quotas, and fair scheduling;
- shared/private credential queue routing;
- PostgreSQL claims with multi-scheduler coordination;
- customer Java scheduler adapter;
- recurring schedules and calendar rules;
- queue-position and start-time estimates;
- recovery for a broker-accepted message lost before worker claim.
