# AgentGate Refactor-1 Architecture

This document defines the target architecture. It is not an inventory of already
implemented files. See [`project-progress.md`](project-progress.md) for the current
implementation status and remaining work.

## Purpose

AgentGate is an Agent Evaluation Harness. It executes versioned test Cases against
external Agent or Skill targets, captures behavior, evaluates outcomes, calculates
quality metrics, applies release gates, supports regression comparison, and exposes the
results through Web, CLI, and HTTP interfaces.

It also supports static Skill evaluation before execution by checking Skill descriptions,
conflicts, confusion risk, and Prompt alignment.

AgentGate is not a complete enterprise control plane, scheduler, observability platform,
Agent builder, or secret-management system. Production deployments integrate with those
systems through explicit adapters.

## System View

```text
External Agent platform
        |
        | Target metadata and exact versions
        v
Target catalog adapter --------------------+
        |                                   |
        v                                   v
TargetDescriptor                    skill_analysis/
        |                            static findings
        v
RunManifest
        |
        v
Run management -> job dispatcher -> RunEngine
                                      |
                                      v
                              Target execution adapter
                                      |
                                      v
                         Agent execution + Trace + Artifacts
                                      |
                                      v
                                  Evaluators
                                      |
                                      v
                                    Results
                                      |
                         +------------+-------------+
                         v                          v
                      Metrics                  Comparison
                         |
                         v
                    Release Gate
                         |
                         v
                       Report
                         |
              +----------+----------+
              v          v          v
             Web        CLI       FastAPI
```

## Backend Structure

```text
src/agentgate/
├── domain/
├── dataset/
├── run/
├── trace/
├── evaluator/
├── result/
├── skill_analysis/
├── optimizer/
├── integrations/
├── application/
├── storage/
├── cli/
└── server/
```

`web/` is the separate Vue frontend.

### Domain

`domain/` is the single source of truth for immutable business models and invariants.

```text
domain/
├── __init__.py
├── base.py
├── case.py
├── dataset.py
├── expectation.py
├── skill_analysis.py
├── target.py
├── evaluator.py
├── run.py
├── trace.py
├── artifact.py
├── result.py
├── metric.py
├── gate.py
└── report.py
```

Agent and AgentVersion are externally owned. AgentGate records exact Target references,
normalized descriptors where required, and immutable execution-time snapshots.

### Dataset

```text
dataset/
├── loader.py
├── export.py
├── versioning.py
├── sampling.py
├── generation/          future implementation
└── formats/
```

This capability loads, exports, versions, samples, and eventually generates Datasets.
A Dataset is a versioned collection of Cases. `domain/case.py` defines individual Cases,
while `domain/dataset.py` defines the Dataset aggregate and its versions. Domain
validation remains in `domain/`; persistence remains in `storage/`.

### Run

```text
run/
├── engine.py
├── process_manager.py
├── retry.py
├── artifacts.py
└── target_protocol.py
```

The Run engine executes Cases using one uniform Target Adapter Protocol. Local
parallelism uses isolated Agent processes and Workspaces; retry history is recorded as
Trace events.
Retries apply only to infrastructure failures, never to wrong answers or evaluation
failures.

### Trace

```text
trace/
├── normalizer.py
└── redaction.py
```

OpenTelemetry is the external interchange format. The normalizer converts vendor-specific
attributes into canonical domain Trace semantics; redaction protects sensitive content
before Judge, UI, dataset, or external-output use.

### Evaluator

```text
evaluator/
├── evaluator_protocol.py
├── executor.py
├── models.py
├── hybrid.py
├── rule/
└── judge/
```

Rule evaluators perform deterministic checks such as JSON structure and field-value
validation, required or forbidden Tools, Tool arguments, policy, state, and trajectory.
Judge evaluators perform semantic checks. Hybrid evaluators combine explicitly defined
Rule and Judge semantics. Runtime-only evaluator models may remain in `evaluator/models.py`.

### Result

```text
result/
├── metrics.py
├── gate.py
├── report.py
└── comparison.py
```

Metrics summarize one Run, Gate determines whether it meets configured thresholds, Report
assembles its conclusion, and Comparison explains differences between completed Runs.
Comparison is not limited to A/B testing.

### Static Skill Evaluation

```text
skill_analysis/
├── __init__.py
├── analyzer_protocol.py
├── models.py
├── description_quality.py
├── skill_relationships.py
├── prompt_alignment.py
├── llm_semantic.py
└── pipeline.py
```

This capability inspects Target definitions without executing Cases. It produces static
findings and a static risk matrix. It must not emit fake dynamic Results or call its risk
matrix an observed confusion matrix.

### Optimizer

`optimizer/` is retained for later implementation of Badcase clustering, observed
confusion matrices, root-cause hypotheses, and reviewable suggestions based on completed
Runs, Results, and Traces. Detailed design is intentionally deferred until implementation.

### Integrations

```text
integrations/
├── targets/
│   ├── http_agent.py
│   ├── process_agent.py
│   ├── demo_loan.py
│   └── trace_replay.py
├── observability/
│   ├── in_memory.py
│   └── otlp_http_receiver.py
├── model_providers/
│   └── openai_compatible.py
├── job_dispatchers/
│   └── celery.py
└── result_outputs/       create only when an external output is implemented
```

Platform-specific Target adapters such as Dify or Coze are added only when generic HTTP
configuration cannot express their behavior. Integration modules translate protocols;
they do not own business invariants or application workflows.

### Application

```text
application/
├── run_management.py
├── dataset_management.py
├── dataset_generation.py      future
├── target_catalog.py
├── evaluator_management.py
├── skill_analysis.py
├── result_reader.py
└── lineage_queries.py
```

The application layer coordinates complete use cases. It resolves versions, invokes core
capabilities, controls transactions through repositories, and provides shared boundaries
to FastAPI, CLI, Celery, and external control planes.

### Storage

```text
storage/
├── __init__.py
├── repository.py
├── sqlite.py
└── artifacts.py
```

SQLite is authoritative for POC Runs and Results. Redis and Celery state is operational
only. Artifact metadata is stored in the database while large bytes use local Artifact
storage. PostgreSQL and object storage are later adapters behind the same contracts.

### CLI

```text
cli/
├── __init__.py
├── main.py
├── run_commands.py
├── dataset_commands.py
└── result_commands.py
```

The CLI parses commands, calls application services, presents output, and maps Gate
conclusions to documented CI exit codes. It does not bypass the application layer.

### Server

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
    └── skill_analysis.py
```

FastAPI is the HTTP transport. Long evaluations are dispatched outside the request
process and normally return HTTP 202. Routes validate and translate HTTP data but do not
implement business workflows or query SQLite directly.

### Web

```text
web/src/
├── main.ts
├── App.vue
├── router/
├── layouts/
├── pages/
├── components/
├── composables/
├── api/
├── types/
└── styles/
```

The Vue 3 target application uses Vue Router to map seven planned POC routes to pages: Overview,
Evaluation Tasks, Results Center, Result Detail, Dataset Management, Evaluator Management,
and Static Skill Analysis. Optimization Center is deferred.

`App.vue` only mounts the application layout and router view. Pages coordinate workflows,
composables own reusable client state, API modules call FastAPI, and components communicate
through typed props and events. Pinia is added only when real cross-route mutable state
appears. Detailed frontend boundaries are documented in `docs/web/README.md`.

## Primary Workflows

### Dynamic Evaluation

```text
Web/CLI/API
  -> application/run_management.py
  -> resolve exact Dataset, Target, and Evaluator versions
  -> construct immutable domain.RunManifest
  -> persist pending Run
  -> Web/API submission dispatches its run_id through Celery
  -> a direct CLI caller may invoke the same application execution boundary
  -> run/engine.py executes each Case
  -> Target adapter invokes the external Agent or Skill
  -> correlate and normalize Trace; collect Artifact references
  -> evaluator/executor.py runs selected evaluators
  -> result/ calculates Metrics, Gate, and Report
  -> persist and expose through result_reader.py
```

### Static Skill Evaluation

```text
Web/API or evaluation preparation
  -> application/skill_analysis.py
  -> target_catalog.py resolves exact TargetDescriptor
  -> skill_analysis/pipeline.py runs selected analyzers
  -> persist immutable SkillAnalysisReport
  -> reviewer accepts, dismisses, or defers findings separately
```

### Trace Replay

```text
Existing external Trace
  -> integrations/targets/trace_replay.py
  -> normalize and redact
  -> evaluate without reinvoking the Agent
```

## Dependency Rules

```text
server/  cli/  job dispatchers
            |
            v
       application/
            |
            v
dataset/ run/ trace/ evaluator/ result/ skill_analysis/
            |
            v
          domain/

storage/ and integrations/ implement contracts used by application/core capabilities.
domain/ depends on none of them.
```

Core rules:

1. Domain models are immutable, version-specific, UTC-based, and free of side effects.
2. No plaintext credential is stored; persisted configuration uses `credential_ref`.
3. RunManifest records exact versions and hashes needed for reproducibility.
4. Feature modules do not query SQLite or expose HTTP directly.
5. Server, CLI, and Celery all call the same application boundaries.
6. Target-specific behavior remains behind adapters.
7. OTel remains the Trace transport standard; AgentGate normalizes semantics rather than
   inventing a competing wire format.
8. Artifact records reference large files instead of embedding their bytes.
9. Static findings remain distinct from observed execution Results.
10. Suggestions are reviewable and do not automatically modify customer Agents.

## Deferred Or Removed Packages

- `experiment/`: removed from refactor-1. General regression comparison belongs in
  `result/comparison.py`; the initial A/B workflow belongs in
  `application/ab_testing.py`. Extract a focused package only if experimental assignment
  and design become independently complex.
- `lineage/`: removed as a top-level package. RunManifest plus indexed Run-asset
  references and `application/lineage_queries.py` satisfy basic lineage needs.
- `queue/`: removed as a domain package. Celery dispatch belongs in
  `integrations/job_dispatchers/`; AgentGate storage remains authoritative.
- `control/` and `control_plane/`: target removal after deferred CLI callers migrate to
  capability-oriented `application/` orchestration. AgentGate does not rebuild the
  customer enterprise control plane.
- `demo/`: currently contains the working POC Agent. Moving standalone demonstration
  behavior under `examples/` remains cleanup work after runtime composition stabilizes.

## Refactor Principle

The working P1 demo is the behavioral baseline. Refactor-1 preserves proven execution,
evaluation, metric, gate, trace-ingestion, and Web behavior while moving responsibilities
to the boundaries above. Empty scaffold files do not override working code. Each move must
retain or add focused tests before obsolete modules are removed.

Detailed decisions and reconciliation notes remain in
[`architecture-review-ledger.md`](architecture-review-ledger.md).
