# Evaluator Refactor Plan

## Status

This is the approved design for the AgentGate P1 evaluator refactor and is implemented
on `goal/p1-demo`. See `docs/progress.md` for current verification evidence and
remaining P2 work.

The product categories are Rule, LLM-as-a-Judge, and Hybrid. There is no Composite
product category. Pure Rule aggregation belongs to Metric and Gate. P1 implements Rule
evaluators only; LLM Judge and Hybrid keep version-1 data contracts but no runtime code.

## 1. Architecture

```text
domain/       Shared, validated data objects
evaluator/    Evaluation behavior and algorithms
result/       Report metric calculation and gate decisions
run/          Orchestration of a complete run
```

Dependencies point toward the domain layer:

```text
evaluator ─┐
result    ─┼──→ domain
run       ─┤
storage   ─┤
server    ─┘
```

The domain layer must not import evaluator, result, run, storage, or server
implementations. Pydantic supplies validation and JSON serialization. AgentGate defines
a configured `DomainModel` base class on top of Pydantic.

### Terminology

```text
Case          One test scenario
Dataset       A named, versioned collection of Cases
Expectation   One value the target agent is expected to produce
Condition     The requirement an expected value must satisfy
Evaluator     Executes checks for one quality metric
Operator      Reusable comparison algorithm used by Rule evaluators
CheckResult   Detailed outcome for one tested item
FailureObservation Trace-sequenced evidence of where one check first failed
EvaluationErrorEvidence Technical evidence for evaluator crash, timeout, or invalid output
Outcome       Evaluation status: pass, fail, review, not applicable, or error
Result        Outcome from one evaluator for one case
MetricPlan    Immutable rules for calculating report statistics
MetricSummary Statistics calculated from multiple Results
GateSpec      Immutable rules for making a release decision
GateDecision  Release decision derived from Results
RunReport     Presentation container for run, Results, metrics, and Gate
Trace         Vendor-neutral record of execution spans and final values
FailureStage  Where a failure was first observed; not a Metric
```

## 2. Domain models

```text
src/agentgate/domain/
├── __init__.py
├── base.py
├── expectation.py
├── case.py
├── trace.py
├── evaluation.py
├── result.py
├── metric.py
├── gate.py
├── run.py
└── report.py
```

### `domain/base.py`

Define the shared Pydantic base:

```python
class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
```

`frozen=True` is only shallow. `domain/base.py` must also define recursively immutable
JSON containers and canonical serialization:

```text
FrozenJsonObject  immutable Mapping[str, FrozenJsonValue]
tuple             immutable JSON array representation
freeze_json()     recursively copy dict/list input into immutable containers
canonical_json()  deterministic UTF-8 JSON with sorted keys and no NaN/Infinity
content_sha256()  SHA-256 of canonical JSON bytes
```

All arbitrary JSON fields in domain models use these immutable types, including Case input
and initial state, evaluator and Judge config, prompt/rubric content, target config, and
Dataset metadata. Trace attributes and final values use the same representation. Serialization still emits ordinary JSON objects and arrays for SQLite and API
clients.

### Enum placement

Enums define fixed allowed values, but they do not need a miscellaneous `enums.py`. Keep
each enum with the concept that owns it:

```text
domain/evaluation.py  Kind, Dimension, Severity
domain/trace.py       SpanKind
domain/result.py      Outcome, FailureStage
domain/run.py         RunStatus
```

`Outcome` values are `pass`, `fail`, `review`, `not_applicable`, and `error`. `FAIL`
means the target agent failed a valid check. `ERROR` means the evaluator could not
produce a valid judgment because it crashed, timed out, or returned malformed data.

`FailureStage` contains only stages observable from the canonical Trace:

```text
routing
tool_selection
tool_arguments
tool_execution
final_state
final_output
```

Failure stage is not a Metric. A Metric says what quality is measured, while a failure
stage says where failure was first observed. For example, `skill_routing_accuracy` is a
Metric and `routing` is its possible failure stage. The field remains named
`primary_failure_step` to match the product requirement and never claims a proven root
cause.

### `domain/expectation.py`

Use `Expectation`, not `Assertion`, because it describes an expected agent outcome. Keep the
model flat: each concrete expectation directly identifies the value to observe.

`Expectation` is a discriminated union of:

```text
StateExpectation
ToolArgumentExpectation
OutputExpectation
```

Each concrete expectation says where to read the actual value and contains a `condition`
describing what that value must satisfy. `Condition` is a discriminated union of:

```text
Equals
WithinTolerance
WithinRange
MatchesPattern
OneOf
MustBeMissing
MatchesJsonSchema
```

For example, `StateExpectation(path="status", condition=Equals(expected="pending_review"))`
means that final-state status is expected to equal `pending_review`.

Repeated tool-call occurrence supports `first`, `last`, `any`, and `all`. `WithinRange`
requires at least one bound and `minimum <= maximum`. `WithinTolerance` epsilon is
positive. Numeric operators reject booleans. `MatchesPattern` expressions are validated
at model construction.

`MatchesJsonSchema` is represented in the version-1 contract but its operator is not
implemented in P1. Evaluation-plan validation rejects a Dataset that requires it.

### `domain/case.py`

A `Case` is one test scenario. A `Dataset` is a named, versioned collection of Cases. For
example, the P1 high-risk Dataset currently contains one high-risk manual-review Case; a
future Dataset may contain high-risk, low-risk, invalid-input, and missing-identity Cases.
Both models remain in this file because they are small and closely related.

`Case` contains id, name, input, initial state, expected skill, expectations, required
tools, forbidden tools, policy rules, and tags. Remove `expected_state` and
`tool_argument_constraints`; state and tool-argument expectations use `expectations`.
Required and forbidden tools remain explicit collection requirements.

### `domain/trace.py`

Define the vendor-neutral canonical execution record:

```text
Trace
├── spans
│   ├── routing decisions
│   ├── agent activity
│   ├── tool calls
│   ├── state events
│   └── other events
├── final_state   System or business data after execution
└── final_output  Data returned by the target agent
```

There is no separate `final_response` field or failure-stage name. A user-facing message
is part of `final_output`, for example `final_output["message"]`.

OpenTelemetry, Langfuse, and future providers are adapters into this canonical model:

```text
OpenTelemetry ─┐
Langfuse      ─┼──→ AgentGate Trace
Other sources ─┘
```

Ingestion behavior belongs to the existing `trace/` product boundary, not a new
`telemetry/` package:

```text
src/agentgate/trace/
├── receivers/
│   └── otlp_http.py    Receive and parse OTLP/HTTP JSON
├── importers/         Import stored or provider-specific trace formats
└── normalizer.py       Convert imported/received data to canonical AgentGate Trace
```

`domain/trace.py` defines data only and must not import OpenTelemetry, Langfuse, FastAPI,
or other provider SDKs. P1 retains OTLP/HTTP ingestion; a Langfuse importer is future
work.

### `domain/evaluation.py`

Define the persisted `EvaluatorSpec` discriminated union, its Rule, LLM Judge, and Hybrid
variants, `ChildRef`, `MethodRef`, prompt and rubric snapshots, `JudgeConfig`, and
`JudgeEvidence`.

`evaluator_type` selects a complete domain evaluator. `operator` selects a reusable
comparison algorithm. A Rule evaluator that dispatches Conditions dynamically uses
`operator=None`; executed operators are recorded in `Result.methods`. Operator and
operator-version must either both be present or both be absent.

A Hybrid directly references both Rule and LLM Judge children and pins child versions.
Nested Hybrid evaluators are unsupported in version 1.

Judge configuration snapshots immutable prompt and rubric content, not only identifiers
or hashes. Judge evidence records the resolved model, raw response, request identifier,
token usage, and latency. P1 defines these models but produces no Judge or Hybrid result.

### `domain/result.py`

Every successfully attempted test item is retained as a `CheckResult` with id, name,
outcome, score, reason, methods, evidence, and optional `FailureObservation`.

```python
class FailureObservation(DomainModel):
    stage: FailureStage
    observed_at_sequence: int
    span_id: str | None = None
```

Rule evaluators return an internal failure candidate containing stage plus either an
evidence `span_id` or a trace-completion marker. The Runner resolves and validates
`observed_at_sequence` from the canonical Trace; evaluators cannot supply an arbitrary
ordering value. When failure is knowable only
after execution completes, such as a required tool that never appeared, use the logical
trace-completion sequence (`max(span.sequence) + 1`) and leave `span_id=None`. A failed
CheckResult must provide a FailureObservation; PASS, N/A, and evaluator ERROR do not.

Define `EvaluationErrorEvidence` with an error category (`crash`, `timeout`, or
`invalid_output`), sanitized exception type and message, retryable flag, and optional log
or request reference. Do not expose secrets or an unsanitized traceback through the API;
the full traceback remains in server logs.

One evaluator produces one `Result` per case. Result stores run/case identity, evaluator
identity/version/kind, dimension, metric, severity, outcome, nullable score, reason, all
CheckResults, executed methods, evidence, optional JudgeEvidence, optional
EvaluationErrorEvidence, and `primary_failure_step`.

`score=None` is used for both N/A and ERROR because neither is an agent-quality score;
the Outcome distinguishes them. Numeric zero is a measured agent score. The primary
failure step is the stage from the failed CheckResult with the smallest
`observed_at_sequence` and never replaces complete check details. Equal sequences use
stable CheckResult order as a deterministic tie-breaker. An
ERROR never receives a FailureObservation, FailureStage, or
`primary_failure_step`, because the agent was not validly judged.

Initial failure-observation mapping is:

```text
skill routing mismatch             routing at routing-span sequence
forbidden tool present              tool_selection at violating tool-span sequence
required tool missing               tool_selection at trace-completion sequence
tool argument mismatch              tool_arguments at tool-span sequence
tool execution failure              tool_execution at tool-span sequence
final-state mismatch                final_state at state-span sequence
deterministic or judged output      final_output at output-span or completion sequence
policy violation by tool choice     tool_selection at violating tool-span sequence
policy violation by tool outcome    tool_execution at violating tool-span sequence
policy violation in final state     final_state at state-span sequence
```

A policy evaluator may emit multiple failed CheckResults. Its primary failure step is
selected from their evidence sequence; policy has no single hard-coded stage.

### `domain/metric.py`

Define `MetricPlan` and `MetricSummary`. `MetricPlan` is the immutable, versioned
configuration that determines how Results become report statistics. P1 snapshots the
full plan, including primary-only filtering, N/A exclusion, within-Case Result
aggregation, across-Case aggregation, Metric-to-Dimension aggregation, filtered
Metric-to-Kind aggregation, and Dimension-to-Overall aggregation. `MetricSummary` is the calculated data
object. Calculation remains in `result/calc_metrics.py`.

A plan ID or version alone is insufficient: RunSnapshot stores the full plan fields and
its version. Any change in aggregation semantics requires a new version.

```python
class MetricPlan(DomainModel):
    id: str
    version: str
    primary_only: bool = True
    exclude_not_applicable: bool = True
    result_within_case_aggregation: Literal["equal_mean"] = "equal_mean"
    case_to_metric_aggregation: Literal["equal_mean"] = "equal_mean"
    metric_to_dimension_aggregation: Literal["equal_mean"] = "equal_mean"
    filtered_metric_to_kind_aggregation: Literal["equal_mean"] = "equal_mean"
    dimension_to_overall_aggregation: Literal["equal_mean"] = "equal_mean"
    overall_source: Literal["dimensions_only"] = "dimensions_only"
```

### `domain/gate.py`

Define `GateSpec` and `GateDecision`. `GateSpec` is the immutable, versioned configuration
containing threshold, blocking-failure behavior, evaluator-error behavior, review behavior,
and empty-result behavior. `GateDecision` is the calculated release decision. The decision algorithm
remains in `result/gate.py`. The 95% P1 threshold must come from the snapshotted GateSpec,
not a hidden function default.

```python
class GateSpec(DomainModel):
    id: str
    version: str
    threshold: float
    blocking_failure: Literal["veto"] = "veto"
    evaluator_error_behavior: Literal["fail"] = "fail"
    review_behavior: Literal["fail"] = "fail"
    empty_result_behavior: Literal["fail"] = "fail"
```

### `domain/run.py`

`RunSnapshot` stores Dataset, target, evaluator specs, `primary_evaluator_ids`, the full
versioned `MetricPlan`, and the full versioned `GateSpec`. P1 marks every selected
evaluator primary. Future Hybrid dependencies may be persisted without being counted
independently by Metric or Gate. These snapshots make historical outcomes explainable
without relying on current function defaults.

RunSnapshot also stores `snapshot_sha256`, calculated from the canonical JSON of all
snapshot content except the hash field itself. Snapshot construction uses a factory that
first deep-copies and freezes all source data, then computes the canonical JSON and hash.
Repository reads verify the hash before returning a Run; a mismatch is a persistence
integrity error, not an evaluator FAIL.

A Run may finish with `RunStatus.COMPLETED` while containing evaluator ERROR Results,
because execution completed and produced a report; its Gate fails closed. `RunStatus.FAILED`
is reserved for unrecoverable target execution, scheduler, storage, or orchestration
failures that prevent a complete report.

```text
RunSnapshot
├── dataset
├── target
├── evaluator_specs
├── primary_evaluator_ids
├── metric_plan + version
├── gate_spec + version
└── snapshot_sha256
```

The immutable typed snapshot is authoritative during execution. Its canonical JSON is
authoritative for persistence, and `snapshot_sha256` proves which exact Dataset, target,
evaluator, MetricPlan, and GateSpec configuration produced the run.

### `domain/report.py`

Define `RunReport` only. It is the API and presentation container that references Run,
raw Results, MetricSummary objects, and GateDecision. Report does not own metric or Gate
semantics; it presents their outputs together with detailed Result/CheckResult evidence.

For the POC, remove `src/agentgate/contracts.py` and update every internal import to use
`agentgate.domain`. Compatibility aliases are deferred until a stable public API has real
external consumers.

## 3. Evaluator runtime

```text
src/agentgate/evaluator/
├── __init__.py
├── models.py
├── base.py
├── registry.py
├── validation.py
├── observations.py
├── calc_score.py
├── runner.py
├── operators/
│   ├── __init__.py
│   ├── comparison.py
│   └── collection.py
├── rules/
│   ├── __init__.py
│   ├── routing.py
│   ├── tool_use.py
│   ├── state.py
│   └── policy.py
├── llm_judge/README.md
└── hybrid/README.md
```

`evaluator/models.py` contains runtime-only `Evaluation`, `Observation`, and
`OperatorOutcome` objects. They are not persisted API contracts.

### Validation

`evaluator/validation.py` defines:

```python
validate_evaluation_plan(dataset, evaluators)
```

It runs before Run persistence and rejects duplicate IDs, unknown implementations, kind
mismatches, unknown or version-mismatched operators, unsupported Case Conditions,
invalid Hybrid children, nested Hybrid, Hybrid definitions lacking both Rule and LLM
Judge children, and one Metric ID being assigned to multiple Dimensions. This is runtime configuration validation, not a test helper.

### Observations and operators

`evaluator/observations.py` extracts actual values from Trace according to a concrete
Expectation and handles repeated-call occurrence. Operators compare one observed value
with one Condition and know nothing about Case, Trace, Metric, or Gate.

The observation layer defines an internal, non-serializable `MISSING` sentinel. It must
never collapse a missing path into Python `None`:

```text
{"value": null}  → observed value is None
{}               → observed value is MISSING
```

`MustBeMissing` passes only for `MISSING`. It fails for a present field whose value is
`None`. Conversely, `Equals(expected=None)` passes for a present null and fails for
`MISSING`. Other value Conditions fail when their declared path is MISSING. `MISSING` is
internal to `evaluator/observations.py` and is never persisted in Result or returned by
the API.

Generic Condition operators in P1 use readable names:

```text
equals
within_tolerance
within_range
matches_pattern
is_one_of
must_be_missing
```

Two collection operators are internal to specialized tool evaluators:

```text
contains_all   required_tool checks that every required tool was called
contains_none  forbidden_tool checks that no forbidden tool was called
```

They do not consume generic Conditions because `required_tools` and `forbidden_tools`
remain explicit Case fields. Adding equivalent collection Conditions would create two
ways to express the same requirement. `appears_in_order` is deferred until a real
tool-order evaluator and sequence expectation are introduced. JSON Schema execution is
also deferred.

### Evaluator-level score

`evaluator/calc_score.py` converts multiple CheckResults from one evaluator and one case
into one Result:

```text
No applicable checks:              NOT_APPLICABLE, score None
All applicable checks pass:        PASS, score 1.0
At least one applicable check fails: FAIL, passed/applicable score
```

Evaluator crash, timeout, or malformed return data does not go through normal check-score
calculation. The Runner creates a Result with `outcome=ERROR`, `score=None`, empty or
partial checks as appropriate, structured EvaluationErrorEvidence, and no FailureObservation or FailureStage.

Not-applicable checks do not enter the denominator. All details remain in Result.
Executed methods are deduplicated in stable order. `calc_score.py` selects the earliest
failed CheckResult by `FailureObservation.observed_at_sequence`; enum declaration order
is never used. The selected observation stage becomes `primary_failure_step`.

This differs from report metric calculation: `calc_score.py` scores expectations inside
one evaluator Result; `result/calc_metrics.py` aggregates many persisted Results.

### P1 Rule evaluators

Implement `skill_routing`, `required_tool`, `forbidden_tool`, `tool_arguments`,
`final_state`, and `policy_compliance` under the four Rule files shown above.

Applicability is explicit. Missing configuration for an evaluator produces
`NOT_APPLICABLE`, not PASS. When a target tool was never called, its tool-argument expectation is N/A because
required-tool owns the missing-tool failure. When the tool was called but the declared
argument path is absent, observation returns MISSING: normal Conditions fail and
`MustBeMissing` passes. A run with only not-applicable
primary results safely fails its Gate.

### Runner

`evaluator/runner.py` provides lazy resolution and memoization, detects duplicate IDs,
missing dependencies, and cycles, and converts internal Evaluation objects to persisted
Results. It catches evaluator-level exceptions and timeouts, logs the full technical
detail, clears resolution state, and emits an ERROR Result so other independent
evaluators can continue. It also validates evaluator return data; malformed Evaluation or
CheckResult data becomes ERROR. It does not catch target-execution, scheduler, storage, or
other run-infrastructure failures as evaluator errors.

## 4. Report metrics and gate

```text
src/agentgate/result/
├── __init__.py
├── calc_metrics.py
├── gate.py
└── service.py
```

`result/calc_metrics.py` consumes `RunSnapshot.metric_plan` and Results to calculate
report summaries. It does not invent aggregation defaults. According to the snapshotted
plan, it filters primary evaluators, excludes not-applicable results from denominators,
and calculates kind summaries such as
Rule-based accuracy, dimension summaries such as Tool accuracy, individual metric
summaries, and overall score.

Aggregation paths are explicit and independent:

```text
Metric summary
1. Group applicable primary Results by (case, metric).
2. Equal-mean multiple Results for the same case and metric.
3. Equal-mean those Case scores across Cases.

Dimension summary
1. Group Metric summaries by Dimension.
2. Equal-mean the Metric summaries in each Dimension.

Kind summary (independent reporting view)
1. Filter primary Results to one evaluator Kind.
2. Recalculate kind-specific Metric summaries with the same Case rules.
3. Equal-mean those filtered Metric summaries.

Overall summary
1. Equal-mean Dimension summaries only.
2. Never include Kind summaries as an additional input.
```

A Metric ID must map to exactly one Dimension within a MetricPlan. The same Metric may be
measured by different evaluator Kinds; therefore Kind summaries are calculated from
kind-filtered Results rather than treating a Metric as owned by one Kind. A summary with
no applicable child scores has `score=None`.

The only score-producing path is `Result → Metric → Dimension → Overall`. Kind summaries
are parallel reporting views and never feed Overall, preventing the same Metric from being
counted through both Kind and Dimension paths.

Metric responses identify level (`overall`, `kind`, `dimension`, or `metric`) and report
passed, failed, reviewed, not-applicable, error, and applicable totals. ERROR is excluded
from agent-accuracy denominators and marks the summary incomplete; valid scores may still
be shown but must not hide the error count. P1 implements a minimal versioned
MetricPlan. Rich Metric definitions, directions, weights, and a registry remain P2 work
under a future `agentgate/metric/` module.

`result/gate.py` consumes `RunSnapshot.gate_spec` and primary Results. It applies the
snapshotted threshold and blocking, review, and empty-result behavior. In the P1 GateSpec,
blocking failure vetoes release, any evaluator ERROR fails closed, review prevents automatic release, N/A is excluded, no
applicable evidence fails, Cases are equally weighted, and the configured threshold must
be reached. `result/service.py` coordinates
metric calculation, Gate decision, and RunReport construction.

## 5. Integration

### Trace ingestion boundary

Move `_otlp_value`, `_attributes`, and `_ingest_otlp` out of
`server/application.py` into `trace/receivers/otlp_http.py` and
`trace/normalizer.py`. The receiver parses OTLP/HTTP JSON and delegates canonical-model
construction to the normalizer. Persistence uses the repository boundary.

The FastAPI `POST /v1/traces` route only validates HTTP content type, reads the request
payload, delegates to the trace receiver, and maps receiver errors to HTTP responses. It
does not parse OTLP attributes or construct TraceSpan objects. Keep the separate health
endpoint unchanged.


`run/core.py` validates Dataset and selected evaluators before saving a Run, resolves and
snapshots the full MetricPlan and GateSpec, records `primary_evaluator_ids`, and passes the
immutable snapshot into report and Gate services. Threshold and aggregation behavior must
never come from hidden defaults in calculation functions.

`demo/loan.py` migrates the high-risk Case to Expectations, sets expected skill to
`loan_approval`, and emits a real routing-decision span. Risky continues to violate
blocking policy; fixed continues to pass.

`control_plane/service.py` removes hard-coded evaluator/metric mappings and returns kind,
dimension, metric, severity, evaluator type, operator, and version from each spec.

Update `web/src/api/client.ts`, `web/src/App.vue`, and `web/src/style.css`. The upper
region displays Rule, LLM Judge, and Hybrid categories; only real P1 Rule evaluators are
selectable. The report displays summaries and all checks, distinguishes PASS, FAIL, ERROR,
REVIEW, and N/A, supports nullable scores, and retains trace drill-down.

## 6. A/B consistency

A/B validation is P2 and is not implemented here. Its future location is
`src/agentgate/experiment/validation.py`. It compares RunSnapshots before execution so
Dataset, Expectations, evaluators, operators, and Judge configuration stay controlled
while the target version changes. `Result.methods` is runtime audit evidence, not the
source for pre-run A/B validation.

## 7. Database cutover

Do not implement V1-to-V2 migration. Existing runs are disposable demo data. Verify
against a separate fresh SQLite database first. At deployment, stop the backend, rename
the old database as a backup, start with a fresh `agentgate.db`, run risky and fixed, and
verify persistence, APIs, and UI. Never delete the backup without explicit approval.

`storage/sqlite.py` keeps the existing JSON-document tables, so no SQL schema migration is
needed for the fresh P1 database. Its serializer must write canonical JSON, and Run reads
must verify `snapshot_sha256` before model validation returns the snapshot. Hash mismatch
raises a persistence-integrity error and fails the Run or report operation; it must never
be converted into an evaluator ERROR or agent FAIL. `pyproject.toml` remains unchanged
because JSON Schema execution is deferred.

## 8. Implementation sequence

1. Add `domain/`, remove `contracts.py`, update all imports, and implement Frozen JSON plus canonical hashing.
2. Add version-1 Expectation, evaluator, Result, MetricPlan, GateSpec, RunSnapshot, and report models.
3. Implement registry, validation, observations, and operators.
4. Implement six P1 Rule evaluators and evaluator-level score calculation.
5. Implement report metric calculation and Gate decisions.
6. Update RunEngine, EvaluationService, loan demo, and SQLite canonical snapshot persistence and verification.
7. Move OTLP parsing into `trace/receivers/otlp_http.py` and canonical conversion into `trace/normalizer.py`; leave the server route as a delegate.
8. Update API-facing TypeScript types and Vue UI.
9. Update focused tests and `docs/progress.md`.
10. Run complete backend, frontend, CLI, API, trace-ingestion, and browser verification.
11. Cut over to a fresh SQLite database only after verification.

## 9. Verification

Add `tests/test_snapshot_immutability.py` covering recursive mutation rejection, source
object isolation, stable canonical hashing, repository tamper detection, and unchanged
evaluation behavior after attempted mutation.


```bash
python3 -m pytest -q
python3 -m pip wheel . --no-deps --wheel-dir /tmp/agentgate-wheel
cd web
npm run typecheck
npm run build
npm run test:e2e
```

Required behavior:

- risky Gate fails;
- fixed Gate passes and improves over risky;
- blocking failure cannot be averaged away at a 95% threshold;
- N/A checks do not raise scores;
- present null and missing path remain distinct;
- MustBeMissing passes only for MISSING, while Equals(None) passes only for present null;
- no applicable primary evidence fails the Gate;
- evaluator crash, timeout, and malformed return each produce ERROR with score None;
- ERROR contains sanitized technical evidence and no FailureObservation or FailureStage;
- primary failure ordering uses TraceSpan sequence, never FailureStage enum order;
- policy violations select tool-selection, tool-execution, or final-state stage from their earliest evidence;
- any primary ERROR fails the Gate closed without counting as an agent failure;
- independent evaluators continue after one evaluator ERROR;
- routing evaluation consumes a real routing span;
- OTLP/HTTP receiver tests exercise real POST ingestion;
- the server route delegates and contains no OTLP attribute parsing or TraceSpan construction;
- the health endpoint remains separate from trace ingestion;
- receiver and normalizer unit tests produce canonical AgentGate Trace objects;
- reports retain every CheckResult and expose evaluator ERROR separately;
- summaries include Rule-based, dimension, metric, and overall results;
- Metric IDs cannot span multiple Dimensions in one MetricPlan;
- Kind summaries use kind-filtered Metric summaries and never feed Overall;
- Overall equals the mean of Dimension summaries only, with no Kind/Dimension double counting;
- nested snapshot mappings and sequences reject mutation;
- mutating source dictionaries after snapshot construction cannot change snapshot content or evaluation behavior;
- semantically identical snapshot input produces identical canonical JSON and SHA-256;
- repository read rejects a tampered snapshot whose canonical content does not match `snapshot_sha256`;
- SQLite saves and reads new Run, Trace, and Result documents;
- CLI and FastAPI both execute the demo;
- desktop and mobile browser checks pass.

## 10. Explicitly deferred

- LLM Judge runtime
- Hybrid runtime
- nested Hybrid
- rule-then-judge execution
- A/B consistency enforcement
- rich MetricDefinition, configurable direction/weights, and registry
- JSON Schema operator and dependency
- `appears_in_order` operator, sequence expectation, and tool-order evaluator
- V1 payload migration
- production scheduler behavior
- Langfuse trace importer under `trace/importers/`
