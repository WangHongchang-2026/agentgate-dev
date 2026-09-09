# Server Implementation Plan

Last updated: 2026-09-09

Status: the modular Server, asynchronous HTTP 202 Run slice, Run cancellation API, and
historical Run rerun API are implemented. Submission, activity, per-Run status,
cancellation, rerun, completed reports,
and stale-Run reconciliation follow `docs/job-dispatcher/implementation-plan.md`.

## 1. Purpose

The Server exposes AgentGate Application use cases through HTTP for the Vue POC and
future external integrations. FastAPI remains the transport because the project already
uses Python and Pydantic, and the current POC API is operational.

```text
HTTP request
  -> FastAPI validation
  -> Application use case
  -> Domain or application result
  -> HTTP response
```

The Server is not an Eval Engine, scheduler, repository, or business-service layer.

## 2. Final Structure

```text
server/
├── __init__.py
├── app.py
├── dependencies.py
├── errors.py
└── routes/
    ├── __init__.py
    ├── system.py
    ├── runs.py
    ├── datasets.py
    ├── catalogs.py
    ├── results.py
    ├── telemetry.py
    └── skill_analysis.py       future
```

Only files with current endpoints are created during this migration. Empty future route
modules are not created.

## 3. Ownership Rules

Server owns:

- HTTP paths, methods, status codes, headers, and content types;
- request/response schemas that exist only for HTTP;
- FastAPI dependency wiring and application lifespan;
- CORS and transport-level body limits;
- conversion of typed application/integration failures into stable HTTP errors;
- router registration and OpenAPI exposure.

Server does not own:

- Dataset, Run, Target, Evaluator, Result, or Trace invariants;
- direct SQLite queries or repository-specific behavior;
- Agent invocation, Case execution, Trace normalization, or evaluator execution;
- metric, report, gate, optimization, or lineage algorithms;
- Celery implementation or customer scheduler state;
- UI labels, chart data formatting, or frontend state.

## 4. Module Contracts

### `app.py`

- Provides `create_app(database_path=None)` and the default ASGI `app`.
- Creates process-lifetime infrastructure dependencies.
- Registers middleware, exception handlers, and routers.
- Uses lifespan for resources that require shutdown.
- Does not define business endpoints or execute use cases.

### `dependencies.py`

- Builds and exposes `SQLiteRepository`, `DatasetManagement`, `RunManagement`, and
  `ResultReader` dependencies.
- Provides demo Target snapshot and runtime composition for the current POC.
- Keeps one process-local demo business-state store.
- Does not add an external dependency-injection framework.
- Does not hide mutable globals behind setter functions.

The POC may use one dependency container stored in `app.state`. Routes retrieve typed
dependencies from the request. Production can replace factories without changing route
logic.

### `errors.py`

- Defines stable HTTP error response helpers.
- Maps `LookupError` to not found and validated use-case errors to unprocessable or
  conflict responses.
- Preserves structured Dataset import validation issues.
- Never infer error categories by parsing arbitrary exception messages.
- Never expose credentials, vendor payloads, stack traces, or filesystem paths.

### `routes/system.py`

- Exposes health and readiness.
- Health confirms the HTTP process is alive.
- Readiness may verify required local dependencies when that behavior is implemented.

### `routes/runs.py`

- Lists Runs and accepts evaluation submissions.
- Calls `RunManagement.create_run()` and `dispatch_run()`.
- Submission persists a pending Run, dispatches only its ID, and returns HTTP 202.
- Worker-side `execute_run()` is never called inside the HTTP request.
- `POST /api/runs/{run_id}/cancel` delegates to `RunManagement.cancel_run()` and returns
  the existing `RunProgress` projection.
- Cancellation returns 200 for a successful or idempotent request, 404 for an unknown
  Run, and 409 for a completed or failed Run.
- Cancellation accepts no request body and exposes no force-kill or dispatcher options.
- `POST /api/runs/{run_id}/rerun` creates and asynchronously dispatches a new pending Run
  from a terminal source Run's exact immutable manifest.
- Historical rerun returns 202, accepts no body or configuration overrides, returns 404
  for an unknown source, and returns 409 for a pending or running source.

### `routes/datasets.py`

- Owns Dataset, version, draft, Case, reorder, import, and export HTTP endpoints.
- Delegates every workflow to `DatasetManagement`.
- Keeps small route-specific request models in this file.
- Streams XLSX output and bounds uploads when the existing Dataset format capability is
  exposed.

### `routes/catalogs.py`

- Exposes the POC Target-version and Evaluator lists.
- Uses static demo metadata until `TargetCatalog` and `EvaluatorManagement` exist.
- Does not implement external Target discovery or Evaluator version management itself.
- Presentation labels returned to the Web are English.

### `routes/results.py`

- Exposes overview, Run report, and Trace detail reads through `ResultReader`.
- Does not query the repository or call result formulas directly.
- Case update actions from a result page call Dataset management endpoints rather than
  mutating a completed Result.

### `routes/telemetry.py`

- Owns OTLP/HTTP content negotiation, body handling, and protocol response.
- Delegates ingestion to `integrations/observability/otlp_http_receiver.py`.
- Is not an OTel Collector or long-term Trace store.

### `routes/skill_analysis.py`

Future route for static Skill-analysis submission, report reads, and finding review.
Create it with the first implemented `application/skill_analysis.py` use case.

## 5. POC Call Chain

```text
Vue Web
  -> POST /api/evaluations
  -> routes/runs.py
  -> RunManagement.create_run()
  -> RunManagement.dispatch_run(run_id)
  -> HTTP 202 pending EvaluationRun

Celery worker
  -> receives run_id
  -> RunManagement.execute_run(run_id)
  -> DemoLoanTargetAdapter
  -> persisted terminal EvaluationRun

Cancellation request
  -> POST /api/runs/{run_id}/cancel
  -> routes/runs.py
  -> RunManagement.cancel_run(run_id, dispatcher)
  -> HTTP 200 cancelled RunProgress

Vue Web
  -> GET /api/runs/{run_id}
  -> routes/results.py
  -> ResultReader.get_report()
```

The initial synchronous route checkpoint remains visible in implementation history
below, but it is superseded by the approved Job Dispatcher plan. Scheduler integration
changes dispatch timing, not Run creation or worker execution contracts.

## 6. Current Route Groups

```text
System:       GET /health
Overview:     GET /api/overview
Catalogs:     GET /api/versions, GET /api/evaluators
Runs:         GET /api/runs, POST /api/evaluations,
              POST /api/runs/{run_id}/cancel, POST /api/runs/{run_id}/rerun
Run activity: GET /api/runs/activity, GET /api/runs/{run_id}/status
Results:      GET /api/runs/{run_id}
Traces:       GET /api/runs/{run_id}/traces/{case_id}
Datasets:     /api/datasets/**
Telemetry:    POST /v1/traces
```

Existing paths remain stable during the internal split so the current Web POC does not
require simultaneous frontend changes.

## 7. Source Assessment

### `goal/p1-demo`

Preserve:

- working FastAPI application factory;
- current API paths and Pydantic request validation;
- CORS for local Vite development;
- Dataset CRUD/draft/version/Case endpoints;
- Run, report, overview, catalog, and Trace endpoints;
- lightweight OTLP/HTTP JSON endpoint behavior.

Refactor or reject:

- split the broad `server/application.py` by route ownership;
- remove direct repository access from routes;
- remove dependency on `control_plane/EvaluationService`;
- move OTLP transport implementation to integrations;
- remove empty `routes.py` and `services.py`;
- replace repeated ad hoc exception mapping with typed helpers.

### `integration/p1-new`

Use as design references:

- bounded Excel multipart uploads and streamed XLSX downloads;
- OTLP content-type and content-encoding handling;
- external Target and scheduler endpoint requirements.

Do not copy directly:

- SQLAlchemy Target/Task systems that bypass current Domain and storage contracts;
- mutable module-global service registration;
- background scheduler startup inside FastAPI before the dispatcher design is approved;
- mixed Chinese code comments and response labels;
- manual broad service composition and obsolete models;
- catch-all fallbacks that hide integration failures.

### Current Refactor

Reuse:

- `DatasetManagement`, `RunManagement`, and `ResultReader`;
- `SQLiteRepository` only in dependency construction;
- `DemoLoanTargetAdapter` and `InMemoryTraceCapture` in POC runtime composition;
- existing Pydantic Domain models as response values;
- current Dataset JSON/XLSX format behavior;
- existing FastAPI API tests as route-contract regression tests.

### From Scratch

- typed dependency container;
- capability-oriented routers;
- centralized HTTP error mapping;
- direct Application composition without a control-plane facade;
- focused route tests for each module boundary.

Reuse means preserving validated behavior under current contracts, not copying a broad
module wholesale.

## 8. Error And Security Rules

- Validate request bodies with Pydantic before calling Application code.
- Unknown resources return 404; invalid inputs return 422; state conflicts return 409
  when a typed conflict exists.
- Do not expose exception class names from unexpected failures to remote callers.
- Body limits are enforced before expensive parsing.
- CORS origins come from configuration in production; wildcard credentialed CORS is
  forbidden.
- Authorization headers and credential references are never returned in API payloads.
- OTLP and Dataset uploads have explicit content type and size limits.
- FastAPI routes do not log complete prompts, Tool arguments, uploaded rows, or Trace
  bodies by default.
- A pending Run must be persisted before its ID is submitted to a dispatcher.

## 9. Implementation Sequence

Each file requires source assessment and explicit approval before implementation.

1. [complete] Create `server/dependencies.py` and compose current Application modules plus the demo
   runtime.
2. [complete] Create `server/errors.py` for stable Dataset and application error mapping.
3. [complete] Create `server/routes/system.py`.
4. [complete] Create `server/routes/datasets.py` and preserve current Dataset endpoints.
5. [complete] Create `server/routes/catalogs.py` for current demo Target and Evaluator reads.
6. [complete] Create `server/routes/runs.py` for initial listing and synchronous POC
   submission.
7. [complete] Create `server/routes/results.py` for overview, reports, and Trace reads.
8. [complete] Move OTLP transport to `integrations/observability/otlp_http_receiver.py` and expose it
   through `server/routes/telemetry.py`.
9. [complete] Implement `server/app.py` and register dependencies, middleware, errors, and routers.
10. [complete] Update imports/tests from `server/application.py` to `server/app.py`.
11. [complete] Remove `server/application.py`, empty `server/routes.py`, and empty
    `server/services.py`.
12. [complete] Verify the initial API contracts and Vue POC workflow.
13. [complete] Follow `docs/job-dispatcher/implementation-plan.md` to replace synchronous
    launch with HTTP 202 dispatch.
14. [complete] Add Run activity and per-Run status endpoints.
15. [complete] Verify queue, worker, progress, and terminal-state API behavior.
16. [complete] Add thin Run cancellation routing with stable not-found and lifecycle
    conflict responses.

CLI migration is explicitly deferred. `control_plane/` and `run/core.py` remain only for
CLI until that later phase.

## 10. Test Plan

- application factory supports an isolated temporary SQLite database;
- health endpoint remains available;
- every Dataset route preserves its current successful and invalid workflows;
- launch persists and dispatches a pending Run, then a worker completes the real
  OTel-backed demo Run;
- selected evaluator IDs remain exact;
- Run/report/Trace/overview reads use Application modules;
- unknown resources map to stable HTTP errors;
- pending/running cancellation returns cancelled progress, repeated cancellation is
  idempotent, and completed/failed cancellation returns conflict;
- cancellation routes expose no worker termination or dispatcher controls;
- OTLP rejects unsupported content types and malformed payloads;
- route modules never query SQLite directly;
- current API tests pass without importing `EvaluationService` in Server code;
- complete backend suite passes;
- Vue API paths remain unchanged.

## 11. Coding Rules

- Keep route functions thin and capability-oriented.
- Keep HTTP schemas beside their owning route.
- Prefer FastAPI dependencies and one explicit container over a DI framework.
- Do not create generic `services.py`, `utils.py`, or `schemas.py` dumping grounds.
- Do not use inheritance for route or service composition.
- Do not catch broad exceptions except at one sanitized unexpected-error boundary.
- Keep all code, comments, API messages, and POC labels in English.
- Do not modify Web files during the Server migration.

## 12. Completion Gate

Server refactoring is complete when:

- no Server module imports `control_plane` or `run.core`;
- routes call Application use cases rather than repositories;
- `server/application.py`, `server/routes.py`, and `server/services.py` are removed;
- the current Vue-facing API paths remain functional;
- the demo evaluation uses the new Run Engine and real OTel spans;
- OTLP transport is isolated under integrations;
- focused API tests and the complete backend suite pass;
- Run cancellation calls the Application workflow and never mutates repository state in
  the route.

## 13. Implementation Decisions

### `server/dependencies.py`

Status: implemented; 245 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve isolated SQLite application construction and demo Dataset bootstrap. |
| `integration/p1-new` | Reject mutable global service registration and separate SQLAlchemy Target/Task systems. |
| Current refactor | Reuse Application modules, `DemoLoanTargetAdapter`, and `InMemoryTraceCapture`. |
| From scratch | Implement one explicit dependency container and synchronous demo Run composition. |

### `server/errors.py`

Status: implemented; 250 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Adapt explicit route-context status selection; reject repeated local helpers. |
| `integration/p1-new` | Preserve structured XLSX issue responses only. |
| Current refactor | Reuse bounded `XlsxFormatError` issues. |
| From scratch | Implement small status-specific functions with bounded credential-redacted details. |

### `server/routes/system.py`

Status: implemented; 251 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve the existing `/health` response. |
| `integration/p1-new` | No additional behavior is justified. |
| Current refactor | Reuse FastAPI. |
| From scratch | Move the single process-health route into its capability module. |

### `server/routes/datasets.py`

Status: implemented; 255 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Adapt the existing Dataset CRUD, version, draft, Case, JSON import, and JSON export routes. |
| `integration/p1-new` | Adapt bounded multipart reading and streamed workbook response behavior only. |
| Current refactor | Reuse `DatasetManagement`, `ExportedDataset`, and bounded `XlsxFormatError` issues. |
| From scratch | Add typed dependency access and capability-focused route tests. |

### `server/routes/catalogs.py`

Status: implemented; 257 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Adapt `/api/versions`, `/api/evaluators`, and their current response shapes. |
| `integration/p1-new` | Reject its broader service coupling; it adds no required POC catalog behavior. |
| Current refactor | Reuse `LoanAgent.versions` and immutable `EVALUATORS`. |
| From scratch | Add a read-only router, explicit English display labels, and focused contract tests. |

### `server/routes/runs.py`

Status: asynchronous dispatch, activity, status, cancellation, and historical rerun
endpoints implemented; 780 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Adapt `/api/runs`, `/api/evaluations`, and the current launch request. |
| `integration/p1-new` | Adapt terminal-source validation only; reject obsolete models, Target overrides, single-Case comparison coupling, and broad service ownership. |
| Current refactor | Reuse `ResultReader.list_runs()` and the existing launch request while replacing `ServerDependencies.execute_demo_run()`. |
| From scratch | Add HTTP 202 dispatch plus activity and status routes through Application services. |
| `goal/p1-demo` and `integration/p1-new` | Reuse no Run cancellation route; neither reference provides the approved API workflow. |
| Current refactor | Reuse `RunManagement.cancel_run()`, `ResultReader.get_run_progress()`, and stable not-found/conflict helpers. |
| From scratch | Add the bodyless cancellation endpoint, lifecycle error mapping, and focused API contract tests. |
| Current refactor | Reuse `RunManagement.create_rerun()`, `dispatch_run()`, `ResultReader.get_run_progress()`, and stable error helpers. |
| From scratch | Add a bodyless HTTP 202 rerun endpoint that exposes no historical configuration overrides. |

### `server/routes/results.py`

Status: implemented; 263 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Adapt overview, completed report, and Trace read endpoints. |
| `integration/p1-new` | Keep rerun, comparison, and regression mutations out of Results routes; those belong to their owning Application and HTTP capabilities. |
| Current refactor | Reuse `ResultReader` exclusively. |
| From scratch | Add focused tests for successful, missing, and pending reads. |

### `server/routes/telemetry.py`

Status: implemented; 267 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Move and preserve OTLP/HTTP JSON normalization and persistence. |
| `integration/p1-new` | Adapt bounded request handling; defer gzip and protobuf support. |
| Current refactor | Reuse Trace normalization and the typed Server dependency container. |
| From scratch | Add a JSON-only transport router and focused media-type, payload, and size tests. |

### `server/app.py`

Status: implemented; 270 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Adapt the FastAPI factory, metadata, local Vite CORS, and default ASGI application. |
| `integration/p1-new` | Reject scheduler startup, mutable globals, extra databases, and background threads. |
| Current refactor | Reuse `build_dependencies()` and all capability-oriented routers. |
| From scratch | Add factory tests for route registration, dependency ownership, CORS, and a complete demo workflow. |

### Legacy Server removal

Status: implemented; 270 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Remove the replaced monolithic `server/application.py` and empty `server/services.py`. |
| `integration/p1-new` | No code is reused. |
| Current refactor | Make `server/app.py` the only ASGI entry point. |
| From scratch | Update test imports and the Playwright server command without changing Vue source. |
