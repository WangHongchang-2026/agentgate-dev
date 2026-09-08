# Optimizer Implementation Plan

Status: implemented and verified on `feature/optimizer` for the POC.

## Scope

AgentGate analyzes one completed Evaluation Run and returns:

- deterministic clusters of failed Evaluation Results;
- an observed expected-versus-actual Skill-routing confusion matrix;
- evidence-backed possible root causes;
- prioritized recommendations that always require human review.

The report is calculated from the immutable Run manifest and persisted Results. An
optional exact static Skill-analysis report may provide corroborating definition
evidence. The POC returns the report without persisting it.

## Source Assessment

### `goal/p1-demo`

The branch contains only one-line placeholders for clustering, root causes, and
suggestions. It contains no optimization domain model, pipeline, application workflow,
storage behavior, or API to preserve.

### `team/integration-p1-new`

The branch contains the same placeholders and no optimizer behavior to adapt. Its useful
conceptual boundary is preserved: optimization consumes real Results and Trace-linked
evidence rather than manufacturing dynamic conclusions from static definitions.

### Current refactor

The implementation is written from scratch against the current immutable Run, Dataset,
Target, Result, routing-check, and Skill-analysis contracts. It composes the existing
repository and server boundaries without adding a generic service, registry, plugin
framework, or storage table.

## Implemented Tree

```text
src/agentgate/
├── domain/
│   ├── __init__.py
│   └── optimization.py
├── optimizer/
│   ├── __init__.py
│   ├── clustering.py
│   ├── confusion_matrix.py
│   ├── pipeline.py
│   ├── root_cause.py
│   └── suggestions.py
├── application/
│   ├── __init__.py
│   └── optimization_analysis.py
└── server/
    ├── app.py
    ├── dependencies.py
    └── routes/
        └── optimizer.py

tests/
├── test_optimization_application.py
├── test_optimization_models.py
├── test_optimizer_clustering.py
├── test_optimizer_confusion_matrix.py
├── test_optimizer_pipeline.py
├── test_optimizer_root_cause.py
├── test_optimizer_suggestions.py
└── test_server_optimizer_routes.py
```

## Ownership

| File | Responsibility |
|---|---|
| `domain/optimization.py` | Immutable optimization output contracts |
| `optimizer/clustering.py` | Deterministic grouping of failed Results |
| `optimizer/confusion_matrix.py` | Observed routing matrix calculation |
| `optimizer/root_cause.py` | Evidence-ranked possible-cause hypotheses |
| `optimizer/suggestions.py` | Targeted, prioritized, human-reviewed recommendations |
| `optimizer/pipeline.py` | Pure composition of all optimizer algorithms |
| `application/optimization_analysis.py` | Repository reads and analysis orchestration |
| `server/routes/optimizer.py` | HTTP parameters, response contract, and error mapping |
| `server/dependencies.py` | Process-level application composition |
| `server/app.py` | Router registration |

No optimizer algorithm belongs in the domain, application, storage, or HTTP layers.

## Data Flow

```text
GET /api/runs/{run_id}/optimization
        |
        v
OptimizationAnalysis.analyze_run(...)
        |
        +--> load exact EvaluationRun
        +--> load persisted EvaluationResults
        +--> optionally load exact SkillAnalysisReport and current reviews
        |
        v
build_optimization_report(...)
        |
        +--> cluster_failed_results(failed Results)
        +--> build_routing_confusion_matrix(Cases, all Results)
        +--> infer_root_causes(clusters, matrix, static findings)
        +--> build_optimization_suggestions(hypotheses, clusters, findings)
        |
        v
OptimizationReport
```

## Domain Contracts

`FailedResultEvidence` records the exact Run, Case, Result, Trace, Evaluator, metric,
severity, earliest failure stage, explanation, and associated Span IDs.

`FailureCluster` contains one or more failed Results sharing a stable signature. Its
Result count, unique Case count, representatives, dimensions, and share are validated.
A failed Result appears in exactly one cluster within a report.

`RoutingObservation` represents one comparable Skill-route expectation for one Case
turn. `ObservedRoute` distinguishes a specific Skill from explicit `missing` and
`ambiguous` buckets.

`RoutingConfusionMatrix` requires unique coordinates, exactly one cell per observation,
explicit exclusions, and an eligible count equal to all cell counts.

`RootCauseHypothesis` contains explicit cluster, Result, Span, and optional static
finding references. Its language and type deliberately describe a possible cause, not
proven causality.

`OptimizationSuggestion` references its supporting hypotheses and has
`requires_human_review=True` as a literal invariant.

`OptimizationReport` records exact Run, Target, Dataset, and analyzer provenance. Its
content hash excludes `created_at` but includes every analytical output.

## Failure Clustering

`cluster_failed_results(...)` accepts only failed Results from one Run and rejects
duplicate Result IDs.

Each failed Result is one clustering unit. A Case may contribute multiple Results and
therefore multiple clusters. The stable grouping signature is:

```text
primary failure stage
+ Evaluator ID
+ dimension
+ metric
+ Evaluator severity
```

Reason text does not affect the signature because evaluator explanations may vary.
Members are ordered by Case ID and Result ID. At most three Result IDs are selected as
representatives. Cluster IDs use the first 24 characters of the signature SHA-256.

Clusters are ordered by failure count descending, blocking severity first for ties, and
then their stable signature. Shares use failed Results as the denominator.

Semantic or embedding-based clustering is not used in the POC.

## Observed Routing Confusion Matrix

`build_routing_confusion_matrix(...)` inspects every `SkillRouteExpectation` in the
Run's immutable Dataset and correlates checks by:

```text
case_id + turn_id + expectation_id
```

Only `Equals(expected=<nonblank string>)` defines one explicit expected Skill and is
eligible for a matrix row. Other conditions are excluded rather than guessed.

Actual routing is classified as:

- `skill` for a nonblank string;
- `missing` when `actual_missing=True`;
- `ambiguous` for null, blank, numeric, object, or multiple values.

An eligible expectation with no correlated check or multiple correlated checks is
recorded as an explicit exclusion. Both passing and failing checks contribute observed
behavior. Unknown actual Skill IDs remain visible as matrix columns.

Cells, observations, and exclusions have deterministic ordering. Counts reconcile
through domain validation.

## Root-Cause Hypotheses

`infer_root_causes(...)` produces exactly one hypothesis per failure cluster. Generic
hypotheses use `<failure_stage>_failure`. A routing cluster becomes
`routing_confusion` when its Results have missing, ambiguous, or different-Skill routing
observations.

Static findings correlate only to routing mismatches and only when their `skill_ids`
intersect expected or observed Skill IDs. Correct routing observations and unrelated
static findings are not cited.

Confidence is a deterministic evidence-strength ranking, not a probability:

| Evidence | Increase |
|---|---:|
| Base | 0.35 |
| At least two failed Results | +0.10 |
| At least two affected Cases | +0.10 |
| Span evidence | +0.10 |
| Incorrect routing observations | +0.15 |
| Relevant static finding | +0.15 × highest static confidence |

The score is capped at `0.95`. Titles use “Possible” and explanations begin with
“Hypothesis” to avoid claiming proven causality.

## Suggestions

`build_optimization_suggestions(...)` creates one recommendation per hypothesis.

| Evidence | Target |
|---|---|
| Routing plus one implicated Skill | `skill_description` with that Skill ID |
| Routing plus multiple Skills | `skill_routing` |
| Routing without static evidence | `agent_routing` |
| Understanding, planning, interpretation, or final output | `agent_prompt` |
| Context retrieval | `retrieval_configuration` |
| Tool selection, arguments, or execution | `tool_configuration` |
| Final state | `state_management` |
| Mixed or unknown stages | `agent_configuration` |

Priority is deterministic:

- `critical`: blocking evidence and confidence at least `0.75`;
- `high`: blocking evidence, confidence at least `0.70`, or affected share at least
  `0.50`;
- `medium`: confidence at least `0.50` or affected share at least `0.25`;
- `low`: all other cases.

Recommendations are fixed bounded templates. Rationales state affected Result and Case
counts, affected share, and evidence-strength confidence. Suggestion IDs hash their
supporting hypothesis and generated action.

Suggestions do not edit external assets or trigger Runs.

## Pure Pipeline

The public optimizer API is:

```python
build_optimization_report(
    run,
    results,
    static_findings=(),
    analyzer_version="1",
)
```

The Run must be completed, all Results must belong to it, and the analyzer version must
be nonblank. Cases, Target identity/hash, Dataset identity/version/hash, and all other
provenance come from the immutable Run manifest.

Only `Outcome.FAIL` Results are clustered. All Results remain available to the routing
matrix. A successful Run produces no clusters, hypotheses, or suggestions but may still
produce a routing matrix from passing checks.

## Application Workflow

`OptimizationAnalysis.analyze_run(...)` accepts a Run ID and an optional explicit
Skill-analysis report ID.

It does not choose an implicit latest report. When a report is supplied, it must:

- exist;
- have `completed` or `partial` status;
- match the Run's exact Target reference;
- match the Run Target snapshot's descriptor hash.

The workflow loads current reviews and removes findings whose decision is `dismissed`.
Unreviewed, confirmed, accepted-risk, and deferred findings remain eligible evidence.
The workflow then calls the pure pipeline and returns the report without storing it.

## HTTP API

```text
GET /api/runs/{run_id}/optimization
    ?skill_analysis_report_id=<optional exact report ID>
```

The response is the `OptimizationReport` domain contract directly.

| Condition | Status |
|---|---:|
| Run or explicit Skill-analysis report not found | 404 |
| Run not completed | 409 |
| Mismatched, failed, or otherwise invalid analysis input | 422 |

The endpoint is read-only and has no request body.

## Determinism And Safety

For identical immutable inputs:

- cluster, hypothesis, and suggestion IDs are stable;
- all output collections have stable ordering;
- analytical output and report content hashes are stable;
- only `created_at` may differ.

The optimizer consumes already persisted and redacted Result/Span references. It does not
send evidence to a model, resolve credentials, invoke Targets, or expose new secrets.

## Verification

Focused coverage verifies:

- domain invariants and content hashing;
- deterministic clustering and representative selection;
- multi-turn routing correlation, missing/ambiguous buckets, and exclusions;
- routing/static evidence correlation and confidence calculations;
- every suggestion target family and priority threshold;
- pipeline composition and immutable provenance;
- explicit Skill-report selection and dismissed-review filtering;
- HTTP response/error contracts and OpenAPI registration.

The full backend regression passes with `712 passed` and one existing Starlette
TestClient deprecation warning.

## POC Exclusions

The POC does not include:

- semantic, embedding, or LLM-based clustering;
- an LLM root-cause analyzer;
- persisted Optimization Reports or history;
- suggestion review persistence;
- automatic prompt, Skill, Tool, retrieval, or state changes;
- Badcase writeback into Dataset drafts;
- automatic regression Run creation;
- cross-Run trend analysis;
- A/B-specific optimization;
- optimizer CLI or Web pages.

Those capabilities require separate product requirements and architecture checkpoints.
