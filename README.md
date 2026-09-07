# AgentGate

AgentGate is an open-source evaluation harness for enterprise Agents and Skills. It
runs versioned Cases, captures behavior as OpenTelemetry traces, evaluates business
rules, calculates metrics, and makes release-gate decisions.

## Current Status

Refactor-1 is in progress. The Domain, SQLite, Dataset workflow, deterministic loan
demo, core Run Engine, result calculation, modular FastAPI foundation, and asynchronous
Redis/Celery Run workflow are implemented. The Web application can submit Runs, show
queued and running progress, stop polling after terminal state, and open completed reports.

- [Whole-project progress and code locations](docs/project-progress.md)
- [Current architecture](docs/architecture.md)
- [Documentation index](docs/README.md)
- [Product requirements](docs/product-requirements-zh.md)

The current backend regression suite has 289 passing tests. The Web application remains
partially refactored; consult the progress document for the implemented page scope.

## Core Flow

```text
DatasetVersion + TargetSnapshot + EvaluatorSpec
                     |
                     v
                 RunManifest
                     |
                     v
EvaluationRun -> Job dispatcher -> RunEngine
                                    |
                                    v
                           Target adapter -> Agent
                                    |
                                    v
                         Trace -> Evaluators -> Results
                                                |
                                                v
                                  Metrics -> Release Gate -> Report
```

SQLite is authoritative for POC Run state and Results. Redis and Celery provide
asynchronous delivery only; Celery task state is not a business data source.

## Target Layout

```text
src/agentgate/
  domain/          # Immutable business models and invariants
  dataset/         # Dataset loading, formats, export, and version mechanics
  run/             # Case execution engine and Target protocol
  trace/           # Trace normalization and redaction
  evaluator/       # Rule, Judge, and Hybrid evaluation
  result/          # Metrics, release gate, report, and future comparison
  skill_analysis/  # Future static Agent/Skill definition analysis
  optimizer/       # Future badcase analysis and suggestions
  integrations/    # Targets, observability, models, and job dispatchers
  application/     # Use cases shared by HTTP, CLI, and workers
  storage/         # Persistence contracts and SQLite adapter
  cli/             # Deferred command-line transport refactor
  server/          # FastAPI transport

web/               # Vue 3 and TypeScript frontend
docs/              # Active architecture, plans, and progress
examples/          # Example assets and future standalone demo Agents
tests/              # Backend regression suite
```

This is the target layout. Some legacy files remain until their callers are migrated;
the progress checklist records those differences explicitly.

Top-level `case/`, `queue/`, `experiment/`, and `lineage/` packages are not part of the
refactor architecture. Dataset/Case behavior belongs under `domain/`, `dataset/`, and
`application/`. Asynchronous work belongs behind job-dispatch integrations. A/B testing
will compose ordinary Runs and Result comparison when implemented.

## Demo

The current deterministic loan Agent demonstrates real OTel spans and business-policy
evaluation:

- high-risk loans must not be approved directly;
- some decisions require human review;
- Evaluators inspect routing, Tool calls, arguments, policy, and final state;
- a risky Agent version fails while the fixed version passes.

## Local Setup And Operation

Install the Python package and Web dependencies:

```bash
python3 -m pip install -e '.[test]'
cd web
npm install
cd ..
```

Start each process in its own terminal. The API and worker must use the same absolute
SQLite path and Redis URL.

```bash
redis-server --port 6379
```

```bash
AGENTGATE_DB="$PWD/agentgate-demo.db" \
AGENTGATE_REDIS_URL="redis://127.0.0.1:6379/0" \
PYTHONPATH=src \
python3 -m celery \
  -A agentgate.integrations.job_dispatchers.celery:celery_app worker \
  --loglevel=INFO --concurrency=1
```

```bash
AGENTGATE_DB="$PWD/agentgate-demo.db" \
AGENTGATE_REDIS_URL="redis://127.0.0.1:6379/0" \
PYTHONPATH=src \
python3 -m uvicorn agentgate.server.app:app --host 127.0.0.1 --port 8000 --reload
```

```bash
cd web
AGENTGATE_API_TARGET="http://127.0.0.1:8000" npm run dev
```

Open the Vite URL, submit an evaluation, then use **运行队列** to inspect queue position,
Case progress, timing, failures, and recent completed reports.

## Asynchronous Run APIs

- `POST /api/evaluations` persists a pending Run, dispatches only its ID, and returns
  `202 Accepted`.
- `GET /api/runs?status=<status>` lists filterable Run history.
- `GET /api/runs/activity` returns exact lifecycle counts plus queued, running, and
  recent terminal projections.
- `GET /api/runs/{run_id}/status` returns progress, timing, error, and best-effort
  queue position.
- `GET /api/runs/{run_id}` returns the report after completion.

## Verification

```bash
pytest -q
cd web
npm run typecheck
npm run build
npm run test:e2e
```

The Playwright suite starts its own Redis broker, one Celery worker, FastAPI, and Vite.
It requires `redis-server` on `PATH` and a Playwright Chromium installation. Install the
browser once with `npx playwright install chromium` if needed.
