# Domain

The Domain package defines AgentGate's stable business objects and invariants. It is the
single source of truth for Cases, Targets, Runs, Traces, evaluation Results, Metrics, and
Gate decisions. Feature packages operate on these models; they do not redefine them.

## Target Structure

```text
domain/
├── __init__.py
├── base.py
├── case.py
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

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Expose the stable public API of the domain package. |
| `base.py` | Provide immutable model primitives, JSON-safe values, canonical serialization, and content hashing. |
| `case.py` | Define Cases, multi-turn conversations, Datasets, and Dataset versions. |
| `expectation.py` | Describe expected outputs, states, Tool arguments, and validation conditions. |
| `skill_analysis.py` | Define persisted `SkillAnalysisSpec`, findings, reviews, and `SkillAnalysisReport` objects. |
| `target.py` | Represent exact external Agent/Skill identities, descriptors, and immutable execution snapshots. |
| `evaluator.py` | Define versioned Rule, LLM Judge, and Hybrid Evaluator specifications. |
| `run.py` | Define Run configuration, manifest, lifecycle, CaseRuns, and retry Attempts. |
| `trace.py` | Define the normalized, vendor-neutral execution Trace and Spans. |
| `artifact.py` | Define references and metadata for files produced during execution. |
| `result.py` | Define evaluator outcomes, scores, failure attribution, and evidence. |
| `metric.py` | Define metric aggregation configuration and calculated summaries. |
| `gate.py` | Define release-gate rules and pass/fail decisions. |
| `report.py` | Define the composite Run report returned to application readers. |

Agent and AgentVersion are not AgentGate-owned domain objects. The customer platform owns
them; AgentGate records an exact external `TargetRef`, normalized descriptor where needed,
and immutable evaluation-time Target snapshot.

## Relationship

```text
Case + Expectation
        |
        v
TargetDescriptor ----> SkillAnalysisReport

Target + Run ---------> Trace + Artifact
                        |
                        v
                    Evaluator
                        |
                        v
                     Result
                        |
                        v
                Metric + Gate
                        |
                        v
                     Report
```

Modules are divided by stable business concepts, not by Web pages, database tables, or
implementation steps. A separate module is justified when a concept has its own lifecycle,
invariants, or independent reuse. Small supporting objects remain with their owning concept.

## Size Guidance

These ranges guide review and planning; they are not enforced limits.

| Module | Estimated production LOC |
| --- | ---: |
| `__init__.py` | 30-60 |
| `base.py` | 80-130 |
| `case.py` | 130-200 |
| `expectation.py` | 120-180 |
| `skill_analysis.py` | 180-280 |
| `target.py` | 160-240 |
| `evaluator.py` | 140-220 |
| `run.py` | 220-320 |
| `trace.py` | 100-180 |
| `artifact.py` | 60-100 |
| `result.py` | 160-240 |
| `metric.py` | 50-100 |
| `gate.py` | 40-80 |
| `report.py` | 30-70 |
| **Total** | **1,500-2,300** |

Expected domain-test size is approximately 1,200-2,000 lines. When a domain module grows
beyond roughly 300 lines, review whether it contains multiple independent concepts or
workflow/infrastructure logic; do not split a coherent concept merely to satisfy a line
limit.

## Coding Rules

### Dependencies

`domain/` may import the Python standard library, Pydantic, and other `domain/` modules.
It must not import `application/`, `storage/`, `integrations/`, `server/`, `run/`,
`evaluator/`, or `result/`.

### Immutability and invariants

- Domain models are immutable and reject undeclared fields.
- Published versions and execution manifests are immutable records.
- Domain field validation and cross-field invariants belong in this package.
- Dataset-wide rules, legal Run state transitions, Attempt ownership, and Result
  consistency must not be delegated to API or persistence code.
- Changes to versioned objects create a new object or version rather than mutating the
  published object.

### Allowed behavior

Domain models may validate themselves, calculate stable hashes, enforce legal state
transitions, and expose small derived properties. They must not query a database, invoke
an Agent or LLM, read files, send HTTP requests, publish jobs, or calculate a complete
report workflow.

### Naming

Use concept-specific names such as `EvaluatorKind`, `EvaluationDimension`, `RunStatus`,
`AttemptStatus`, and `TargetType`. Avoid ambiguous public names such as `Kind`, `Type`,
`Status`, `Config`, and `Data`.

### Versions and hashes

- A Run manifest records exact Target, Dataset, Evaluator, Prompt, model, Tool/Skill, and
  effective Run-configuration versions or hashes.
- Mutable aliases such as `latest` are never sufficient reproducibility identities.
- Published versions, Target snapshots, and Run manifests use canonical content hashes.
- Runtime progress and timestamps that are not part of configuration must not
  accidentally change a configuration hash.

### Credentials and vendor data

- Persist only an opaque `credential_ref`; never place API keys, passwords, or access
  tokens in a domain model.
- Keep vendor-specific extension data in controlled immutable JSON metadata.
- Do not add Dify-, Coze-, or customer-specific fields to core models.

### Definition versus observation

Keep configuration separate from calculated facts:

- `EvaluatorSpec` defines evaluation; `Result` records its outcome.
- `MetricPlan` defines aggregation; `MetricSummary` records calculated metrics.
- `GateSpec` defines thresholds; `GateDecision` records the decision.
- `TargetSnapshot` identifies what was executed; `Trace` records observed behavior.

### Time

All persisted timestamps are timezone-aware UTC values. Naive and local timestamps are
not accepted.

## Testing Rules

Tests should verify AgentGate invariants rather than retest Pydantic itself. Important
coverage includes:

- invalid lifecycle transitions are rejected;
- duplicate Case IDs are rejected;
- published versions are immutable and reproducible;
- secrets cannot appear in snapshots;
- content hashes survive serialization round trips;
- retry Attempts remain attached to one CaseRun;
- failed Results contain consistent failure evidence;
- completed Runs contain the required completion data.

## Explicit Non-Responsibilities

- Dify, Coze, HTTP, CLI, and model-provider protocol handling belongs in `integrations/`.
- Agent execution and process control belong in `run/`.
- Evaluator algorithms belong in `evaluator/`.
- Metric, Gate, report, and comparison calculations belong in `result/`.
- Use-case orchestration belongs in `application/`.
- Persistence and SQL belong in `storage/`.
- HTTP request/response behavior belongs in `server/`.
- Web visualization belongs in `web/`.
