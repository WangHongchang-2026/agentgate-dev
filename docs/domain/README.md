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

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Expose the stable public API of the domain package. |
| `base.py` | Provide immutable model primitives, JSON-safe values, canonical serialization, and content hashing. |
| `case.py` | Define individual Cases, multi-turn conversations, category, and difficulty. |
| `dataset.py` | Define the Dataset aggregate, Dataset versions, publication state, and collection-wide invariants. |
| `expectation.py` | Describe expected outputs, states, Tool arguments, and validation conditions. |
| `skill_analysis.py` | Define immutable static-analysis findings, reports, and separate human reviews. |
| `target.py` | Represent exact external Agent/Skill identities, descriptors, and immutable execution snapshots. |
| `evaluator.py` | Define one versioned Evaluator specification and exact references for composition. |
| `run.py` | Define immutable Run manifests, Evaluation Run lifecycle, and legal transitions. |
| `trace.py` | Define the normalized, vendor-neutral execution Trace and Spans. |
| `artifact.py` | Define immutable ownership, content identity, and storage metadata for execution-produced files. |
| `result.py` | Define Evaluation results, per-check provenance, failure attribution, Judge records, and evaluator errors. |
| `metric.py` | Define metric aggregation configuration and calculated summaries. |
| `gate.py` | Define release-gate rules and pass/fail decisions. |
| `report.py` | Define the composite Run report returned to application readers. |

## Base Primitives

`base.py` establishes behavior shared by every domain module:

- `DomainModel` makes Pydantic domain values immutable, rejects undeclared fields, and
  validates default values as well as caller-provided values.
- `utcnow()` is the shared factory for timezone-aware UTC timestamps.
- `normalize_utc()` rejects naive datetimes and converts aware datetimes to UTC;
  optional fields handle `None` before calling it.
- `require_non_blank()` is the shared scalar string validator. Domain modules compose it
  inside field validators instead of defining local helpers or validator base classes.
- `find_credential_path()` owns the single credential-key denylist used to prevent
  plaintext secrets from entering domain configuration and metadata.
- `FrozenJsonObject` recursively freezes JSON objects. Nested objects become
  `FrozenJsonObject` instances and arrays become tuples.
- `freeze_json()` converts data entering the domain into immutable JSON values;
  `thaw_json()` converts those values back to ordinary dictionaries and lists at an
  integration or serialization boundary.
- `canonical_json()` sorts object keys and uses stable JSON formatting so logically
  equivalent values have the same serialized representation.
- `content_sha256()` provides content identity from canonical JSON. It does not replace a
  business version such as a Dataset or Evaluator version.

Only JSON-compatible values are accepted. Object keys must be strings, numeric values
must be finite, and arbitrary Python objects are rejected. These restrictions keep
snapshots, manifests, hashes, and persisted representations reproducible across processes.

## Case Models

`CaseTurn` represents one user input and the expected outcomes for that conversation
step. `Case` owns one or more ordered turns plus category, difficulty, tags, notes, and
initial state. Whether a Case is multi-turn is derived from its turn count.

Case-local invariants are enforced during construction: identities cannot be blank, turn
and Expectation IDs must be unique within a Case, and tags cannot contain blank or
duplicate values. Dataset-wide invariants remain the responsibility of
`domain/dataset.py`.

## Expectation Models

An Expectation identifies where actual behavior is observed; a Condition defines how an
observed value is compared. Skill route, Tool presence, Tool arguments, final state, final
output, and policy compliance are separate typed Expectation subjects. Value-oriented
subjects reuse Equals, tolerance, range, regex, one-of, missing-value, and JSON Schema
conditions instead of creating one class for every subject/operator combination.

Expectation models are immutable declarations. Trace extraction, comparison execution,
LLM judging, scoring, and evidence generation remain evaluator responsibilities. Tool
trajectory semantics and file or multimodal expectations are deferred until their
contracts can be defined with the relevant domain modules.

## Dataset Models

`Dataset` owns stable catalog identity and editable display metadata. `DatasetVersion` is
an immutable, ordered snapshot of Cases. Draft edits replace the draft value while keeping
its identity; publishing creates a separately identified, numbered version.

Dataset versions reject duplicate Case IDs. Published versions require at least one Case,
a version number, and a publication timestamp. All timestamps are timezone-aware and
normalized to UTC. The content hash includes Dataset identity, ordered Case content, and
version notes, but excludes lifecycle fields, timestamps, ancestry, and display snapshots.
Publishing transactions and version-number allocation remain outside the domain layer.

## Skill Analysis Models

`SkillAnalysisFinding` records one reviewable static-definition issue with an extensible
check identifier and category, bounded confidence, affected Skill identities, evidence,
and suggestions. Evidence is immutable JSON so analyzers can evolve without changing the
domain contract.

`SkillAnalysisReport` binds findings and a static risk matrix to an exact Target descriptor
hash and analyzer version. Completed reports cannot contain analyzer errors; partial reports
require errors; failed reports contain errors but no analysis output. Report hashes exclude
record identity and creation time. `SkillAnalysisReview` records a later human decision
without modifying the original finding or report.

Analyzer implementations, similarity calculations, LLM calls, persistence, and workflows
remain outside `domain/skill_analysis.py`. Static risk data must not be presented as an
observed routing confusion matrix.

## Target Models

`TargetRef` identifies one exact externally owned Agent or Skill version. Tool and Skill
descriptors normalize customer-platform metadata for dataset generation and static analysis.
`TargetDescriptor` records the complete fetched declaration, while `TargetSnapshot` records
the adapter and non-secret invocation configuration used by one Run.

Prompt hashes are generated or verified when Prompt text is available. Skill identities and
Tool names are unique within their owning descriptor, while duplicate Skill names remain
valid input for ambiguity analysis. Descriptor hashes exclude fetch time; execution snapshot
hashes exclude display name and capture time. Plaintext credential-like fields are rejected
from metadata and invocation configuration; only opaque `credential_ref` values are stored.

Agent and AgentVersion are not AgentGate-owned domain objects. The customer platform owns
them; AgentGate records an exact external `TargetRef`, normalized descriptor where needed,
and immutable evaluation-time Target snapshot.

## Evaluator Models

`EvaluatorSpec` is the single immutable definition for Rule, LLM Judge, and Hybrid
evaluators. `EvaluatorRef` composes exact child versions without a concrete inheritance
hierarchy. Hybrid composition explicitly uses all, any, or weighted-score semantics.
Dimensions and implementation identifiers remain extensible strings.

Rule operators, Judge model and Prompt settings, thresholds, and future method-specific
options live in immutable versioned configuration. LLM Judge model configuration
requires explicit `provider_id` and `model_id`; an optional `credential_ref` never contains
the secret itself. Plaintext credentials are rejected.
Runtime execution belongs in `evaluator/`; scores, verdicts, Judge responses, and method
provenance belong in `domain/result.py`.

## Run Models

`RunManifest` captures the exact published Dataset version, Target snapshot, Evaluator
specifications, Metric plan, Gate specification, and effective timeout, retry, and
parallelism settings for one evaluation. Its content hash excludes creation time.

`EvaluationRun` records only the lifecycle of that complete evaluation. The pure
`transition_run()` function returns a new immutable value for each legal transition.
Per-Case execution records and retry-attempt objects are deferred until AgentGate has real
asynchronous per-Case progress or retry behavior. Retry details can be recorded as Trace
events without adding another domain class.

## Trace Models

`TraceSpan` keeps OTel-compatible Trace and Span identifiers, parent linkage, timing,
status, and an extensible `operation_type` used by evaluators. Attributes and events are
recursively immutable JSON. A missing parent Span is allowed because imported traces may
be partial.

`Trace` binds ordered Spans to one Run and Case. It enforces consistent Trace identity plus
unique Span IDs and execution sequences. Multi-turn outputs are stored in immutable
`turn_outcomes` keyed by Case turn ID; `for_turn()` derives the evidence visible to one turn.
OTLP decoding and vendor semantic-attribute mapping remain outside the domain model.
AgentGate does not redefine the OTel wire format.

## Artifact Models

`Artifact` identifies a file produced by an Agent, Tool, or the evaluation harness during
one exact Run and Case. It stores only immutable metadata and a storage URI; file
bytes remain in local or object storage. The SHA-256 digest identifies and verifies the
actual bytes, while `artifact_type` remains extensible for future file and multimodal outputs.

Artifact collection and hashing belong in `run/artifacts.py`, byte storage belongs in
`storage/artifacts.py`, and content evaluation belongs in `evaluator/`.

## Result Models

`CheckResult` records one concrete Expectation check, including immutable expected and
actual values, exact method implementation references, Trace Span references, and flattened
failure location fields. Failed checks require a stage and execution sequence; a failure
Span must also appear in the check evidence.

`EvaluationResult` records one Evaluator conclusion for one Case and directly identifies the
normalized Trace used. It retains Evaluator display metadata, version, and content hash so
historical results remain independently queryable. Outcome, score, checks, earliest failure,
Judge record, and sanitized error detail are validated as one coherent state. Evaluator error categories are a controlled execution protocol: crash, timeout, or invalid output.

`JudgeRecord.request_sha256` hashes the canonical request JSON actually sent to the Judge,
including rendered messages, rubric, and model parameters but excluding credentials. Only LLM Judge results may contain Judge records; Hybrid results rely on their child
results for Judge provenance. Method provenance exists only on Check results; there
is no duplicated Result-level method or Evidence collection. File and multimodal references
remain deferred until Artifact production and evaluation are implemented.

## Metric Models

`MetricPlan` identifies the exact aggregation algorithm by `id` and `version`; fixed
single-value policy fields are not repeated in every Run manifest. `MetricSummary` stores
a machine key, typed aggregation level, score, and outcome counts. It enforces count totals,
applicable-result totals, score presence, and the reserved `overall` key. Human-readable
labels are resolved by the presentation layer. A metric key may be customer-defined, but
one key cannot belong to multiple dimensions in one Run.

## Gate Models

`ReleaseGateSpec` versions the only configurable POC rule: `minimum_score`. Fixed
fail-closed behavior is expressed once by `classify_release_gate`. `ReleaseGateDecision`
contains the pass/fail outcome, typed reason code, score, threshold, and missing
Case/Evaluator pairs. Counts remain in `MetricSummary`; display text remains in the UI.

## Report Model

`EvaluationReport` is the validated aggregate for one completed Run. It accepts an empty
Result collection so missing execution output can still produce a fail-closed report. It
checks Result identity and Evaluator provenance against `RunManifest`, verifies overall
Metric counts, and confirms the Gate decision against the same primary Results.

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
                EvaluationResult
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
| `case.py` | 80-140 |
| `dataset.py` | 100-170 |
| `expectation.py` | 120-180 |
| `skill_analysis.py` | 180-280 |
| `target.py` | 160-240 |
| `evaluator.py` | 140-220 |
| `run.py` | 220-320 |
| `trace.py` | 100-180 |
| `artifact.py` | 60-100 |
| `result.py` | 160-240 |
| `metric.py` | 50-100 |
| `gate.py` | 90-140 |
| `report.py` | 130-190 |
| **Total** | **1,550-2,400** |

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
- Dataset-wide rules, legal Run state transitions, and Result consistency must not be delegated to API or persistence code.
- Changes to versioned objects create a new object or version rather than mutating the
  published object.

### Allowed behavior

Domain models may validate themselves, calculate stable hashes, enforce legal state
transitions, and expose small derived properties. They must not query a database, invoke
an Agent or LLM, read files, send HTTP requests, publish jobs, or calculate a complete
report workflow.

### Naming

Use concept-specific names such as `EvaluatorKind`, `RunStatus`, and `TargetType`. Avoid ambiguous public names such as `Kind`, `Type`,
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

- `EvaluatorSpec` defines evaluation; `EvaluationResult` records its outcome.
- `MetricPlan` defines aggregation; `MetricSummary` records calculated metrics.
- `ReleaseGateSpec` defines the minimum score; `ReleaseGateDecision` records the decision.
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
