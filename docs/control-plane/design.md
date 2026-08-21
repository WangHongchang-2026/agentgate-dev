# Control Plane Design

## Status

This document separates the current P1 structure from the recommended architecture. Every file or API not marked implemented is a planned boundary. See [progress.md](../progress.md) for verified project status.

## Terms

| Term | Responsibility |
| --- | --- |
| Control panel | Web UI for configuring data, launching evaluations, and reading reports. |
| Control plane | Owns jobs, queueing, scheduling, cancellation, retry, and job status. |
| Execution | AgentGate-owned processing request created when a control-plane Job is submitted for evaluation. |
| Run | AgentGate's persisted domain record for one Execution. |
| Run service | Stable boundary for run creation, idempotency, status, cancellation, and reports. |
| Run engine | Executes Cases, captures traces, and runs evaluators. |

The control panel is a UI. The control plane is a backend orchestration component.

### Ownership rule

```text
Control-plane Job ownership
             !=
AgentGate Execution and Run ownership
```

The active control plane owns `job_id`, queue position, scheduling, retries, and job-level cancellation. AgentGate owns `execution_id`, the internal Run, trace, evaluator results, metrics, and the gate decision. Each accepted Execution maps to exactly one Run. External callers receive only the opaque `execution_id`; the internal `run_id` is not part of the integration contract.

## Workflow comparison

| Stage | AgentGate standalone | External control plane |
| --- | --- | --- |
| User entry | AgentGate Web UI | External Web UI or service |
| Job owner | AgentGate control plane | External control plane |
| Queue and scheduler | AgentGate local POC implementation | External implementation |
| Execution boundary | Local Python `RunExecution` interface | AgentGate Internal Execution API |
| Shared path | Run service -> Run engine -> evaluators | Run service -> Run engine -> evaluators |
| Results | AgentGate job/report API | AgentGate execution/result API |

```text
Standalone:
AgentGate Web -> Web API -> local control plane -> local queue/scheduler
              -> Python RunExecution -> Run service -> Run engine -> evaluators

External:
External Web -> external control plane -> external queue/scheduler
             -> AgentGate Internal Execution API -> integration adapter
             -> Run service -> Run engine -> evaluators
```

Only one control plane owns a job. In external mode, AgentGate does not add a second production queue or scheduler.

## Recommended architecture

```text
                     AgentGate
┌──────────────────────────────────────────────────────┐
│ Public API                 Internal Execution API    │
│     │                               │                │
│ Local control plane                │                │
│     │                               │                │
│ Local queue/scheduler               │                │
│     └───────────────┬───────────────┘                │
│                     v                                │
│                 Run service                          │
│                     │                                │
│                  Run engine                           │
│                     │                                │
│        Target -> Trace -> Evaluators                  │
│                     │                                │
│        Results -> Metrics -> Gate                     │
└──────────────────────────────────────────────────────┘
                            ^
                            │
                  External control plane
                  Queue + scheduler + Job
```

## Current code structure

```text
src/agentgate/
|-- control_plane/
|   `-- service.py
|-- queue/
|   |-- models.py
|   |-- repository.py
|   |-- service.py
|   `-- worker.py
|-- run/
|   |-- core.py
|   |-- engine.py
|   |-- lifecycle.py
|   |-- scheduler.py
|   |-- snapshot.py
|   `-- targets/
|-- server/
|   |-- app.py
|   |-- application.py
|   |-- routes.py
|   `-- services.py
|-- evaluator/
|-- trace/
|-- result/
|-- domain/run.py
`-- storage/
    |-- base.py
    `-- sqlite.py
```

The working P1 path is currently synchronous:

```text
CLI or FastAPI
    -> control_plane/EvaluationService
    -> run/RunEngine
    -> Trace + Evaluators
    -> Results + Metrics + Gate
```

`queue/`, `run/scheduler.py`, and most split `server/` modules are currently scaffolds. They are valid package boundaries and must not be moved under `control_plane/` merely to match a diagram.

## Current and planned file responsibilities

| File or package | Status | Responsibility |
| --- | --- | --- |
| `control_plane/service.py` | Implemented | Local POC evaluation launch and read-model orchestration. It will later own Job lifecycle. |
| `queue/` | Scaffolded | Independent local queue, repository, and worker boundary. |
| `run/core.py` | Implemented | Current RunEngine implementation. |
| `run/scheduler.py` | Scaffolded | Local POC dispatch boundary; not a production scheduler. |
| `server/application.py` | Implemented | Creates FastAPI and currently defines the public API routes. |
| `server/app.py`, `routes.py`, `services.py` | Scaffolded | Future split of application assembly, routes, and dependency wiring. |
| `domain/run.py` | Implemented | Shared Pydantic Run, RunSnapshot, status, and target snapshot models. |
| `storage/base.py` | Implemented | Persistence interfaces suitable for SQLite and later PostgreSQL. |
| `storage/sqlite.py` | Implemented | POC SQLite persistence. |
| `integrations/external_control_plane/` | Planned | Future inbound execution contracts, mapping, authentication, and signed callbacks. |

The external integration is inbound: an external control plane owns scheduling and calls AgentGate. No outbound scheduler adapter is needed for this design.

## Required structural changes

The architecture does not require a mass package move. Future implementation should:

1. Add Job models and lifecycle behavior inside `control_plane/`.
2. Keep `queue/` independent and connect it to the local control plane through interfaces.
3. Add a stable RunService boundary inside `run/` without moving RunEngine.
4. Split HTTP route definitions out of `server/application.py` when the Internal Execution API is implemented.
5. Add `integrations/external_control_plane/` only when external integration work begins.

## API and interface design

### AgentGate Web to local control plane

```text
POST /api/v1/jobs
GET  /api/v1/jobs/{job_id}
POST /api/v1/jobs/{job_id}/cancel
GET  /api/v1/jobs/{job_id}/report
```

These endpoints represent control-plane jobs. A queued job may exist before a Run is created.

### Local control plane to Run service

```python
class RunExecution(Protocol):
    def execute(self, request: RunRequest) -> Run: ...
    def status(self, run_id: str) -> RunStatus: ...
    def cancel(self, run_id: str) -> None: ...
    def report(self, run_id: str) -> RunReport: ...
```

### External control plane to AgentGate Internal Execution API

```text
POST /internal/v1/executions
GET  /internal/v1/executions/{execution_id}
POST /internal/v1/executions/{execution_id}/cancel
GET  /internal/v1/executions/{execution_id}/result
```

A submission must include:

- `external_job_id`
- `idempotency_key`
- immutable `target_snapshot` or a versioned target reference
- `dataset_version`
- `evaluator_versions`
- `execution_config`
- optional `callback_url`

A successful submission returns `execution_id` and status. The external control plane stores the `external_job_id` to `execution_id` mapping. If a callback URL is supplied, AgentGate signs callback requests. Status and result polling always remains available as a fallback.

## Boundary rules

1. Retrying the same idempotency key returns the same Execution and Run instead of duplicating work.
2. RunSnapshot records versioned target, Dataset, evaluators, MetricPlan, and GateSpec.
3. Internal APIs are versioned under `/internal/v1` and use service authentication.
4. AgentGate and an external control plane do not share a database.
5. Cancellation is cooperative and applied by Run service at safe execution boundaries.
6. Historical persisted reports are immutable.
7. Both modes produce the same canonical Run, Trace, Result, Metric, and Gate models.
8. Callback payloads include `execution_id`, status, event time, and signature; callbacks are retried safely and never replace polling.
9. A control-plane retry must reuse its idempotency key. A new key explicitly requests a new Execution.

## P1 boundary

P1 may use a local in-process queue and scheduler for the standalone demo. Interfaces must allow later replacement without changing RunEngine. A production distributed scheduler and full external control-plane integration are outside P1.
