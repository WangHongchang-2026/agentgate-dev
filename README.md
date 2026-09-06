# AgentGate

AgentGate is an open-source evaluation harness for enterprise Agents and Skills. It
runs versioned Cases, captures behavior as OpenTelemetry traces, evaluates business
rules, calculates metrics, and makes release-gate decisions.

## Current Status

Refactor-1 is in progress. The Domain, SQLite, Dataset workflow, deterministic loan
demo, core Run Engine, result calculation, modular FastAPI foundation, and initial job
dispatch boundaries are implemented.

- [Whole-project progress and code locations](docs/project-progress.md)
- [Current architecture](docs/architecture.md)
- [Documentation index](docs/README.md)
- [Product requirements](docs/product-requirements-zh.md)

The current backend regression suite has 278 passing tests. The Web application is
only partially refactored; consult the progress document instead of assuming every
target page or module already exists.

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
asynchronous delivery only and are currently being implemented.

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

Setup and operation commands will be finalized after Celery dispatch and the Web Run
workflow are connected.
