# AgentGate Architecture Review Ledger

Last updated: 2026-09-06

## Review baseline and reconciliation status

The behavioral baseline is the Git branch `goal/p1-demo`; the target structural authority is `docs/architecture.md`.

The Level 2 review is complete. The consolidated target architecture is recorded in
`docs/architecture.md`. The working `goal/p1-demo` behavior remains the migration
baseline even when its current files are renamed, split, or removed.

P1 behavior-preservation inputs include:

- The valid checks formerly in `case/validation.py` have been reassigned: field and
  Dataset invariants live in `domain/`, nonempty publication lives in Dataset
  versioning/application workflows, and evaluator availability remains a later Run
  preflight concern.
- Preserve evaluator/operator implementation and version resolution currently in `evaluator/registry.py`; refactor-1 uses explicit application composition instead of a dynamic registry.
- Preserve per-turn evaluation, dependency resolution, memoization, and error Results currently in `evaluator/runner.py`; the behavior moves behind `evaluator/executor.py`.
- `evaluator/models.py` contains runtime-only, non-persisted evaluation models; the earlier blanket assumption that all models belong in `domain/` was incorrect.
- Preserve the lightweight OTLP ingestion behavior in `trace/receivers/otlp_http.py`; protocol handling moves to `integrations/observability/otlp_http_receiver.py` and semantic conversion remains in `trace/normalizer.py`.
- Preserve the working P1 behavior in `run/core.py` while splitting Engine, Target protocol, application scheduling, and Python-function adapter responsibilities into their confirmed modules.
- Preserve implemented Result behavior while renaming `calc_metrics.py` to `metrics.py` and `service.py` to `report.py`; do not invent a `verdict.py` module.

Current review status:

- Level 1: confirmed.
- Level 2: all target backend folders and `web/` completed.
- `optimizer/`: retained as a future feature boundary; detailed design is deferred until
  implementation.
- `experiment/`, `lineage/`, and `queue/`: removed as top-level `refactor-1` packages for
  the reasons recorded below.
- P1 behavior preservation remains required during implementation for the inputs listed above.
- The backend and Web architecture is consolidated. Implementation begins on a dedicated `refactor-1`
  branch.
- The behavior-preserving source-to-target map and implementation gates are recorded in
  `docs/refactor-implementation-plan.md`.
- Project-authored code and active documentation use English. External data may retain
  its source language.

## Review method

The review follows a strict three-level sequence:

1. Level 1: confirm all top-level folders.
2. Level 2: review one child module, folder, or Python file at a time; discuss responsibility only.
3. Level 3: only after all Level 2 items are confirmed, review classes, functions, protocols, and implementation details inside Python files.

Every discussion response should begin with a `Where are we` navigation block. Cross-module conclusions raised while reviewing another folder must be recorded as Notes rather than lost or implemented immediately.

After all folders and Python files are reviewed, produce one consolidated final Markdown architecture document.

## Navigation map

Current `refactor-1` target backend folders: 13.

1. `domain/`
2. `dataset/`
3. `run/`
4. `trace/`
5. `evaluator/`
6. `result/`
7. `skill_analysis/`
8. `optimizer/`
9. `integrations/`
10. `application/`
11. `storage/`
12. `cli/`
13. `server/`

`web/` is a separate frontend directory and is not included in the 13 backend folders.
Its Level 2 architecture review is complete.

Current Level 2 progress:

- `dataset/`: completed; renamed from the inherited `case/` capability package.
- `run/`: completed.
- `trace/`: completed.
- `evaluator/`: completed.
- `result/`: completed.
- `skill_analysis/`: Level 2 completed; static Skill evaluation remains separate from dynamic Case evaluation.
- `optimizer/`: detailed design deferred until its implementation stage.
- `experiment/`: removed/deferred; a specific `ab_test/` module may be introduced later.
- `lineage/`: no top-level package in `refactor-1`; basic lineage uses indexed Run asset
  references and database queries.
- `queue/`: no top-level package in `refactor-1`; demo async execution uses a Celery
  job dispatcher.
- `integrations/`: completed.
- `application/`: completed.
- `storage/`: completed.
- `cli/`: completed.
- `server/`: completed.
- `domain/`: Level 2 and file-by-file Level 3 implementation review completed.
- Other packages receive Level 3 review when their implementation work begins.
- Consolidated architecture: `docs/architecture.md`.
- Domain implementation and the `domain/__init__.py` public-export audit are complete on `refactor-1`.
- Metric, Gate, and Report implementations are aligned with the final domain contracts.
- Repeated nonblank-string validation is centralized as `domain/base.py::require_non_blank`;
  feature models compose the function without validator inheritance.
- Credential-key detection is centralized as `domain/base.py::find_credential_path` so
  Target and Evaluator configuration cannot drift onto different secret denylists.
- UTC timestamp creation is centralized as `domain/base.py::utcnow`.
- Timezone validation and conversion are centralized as `domain/base.py::normalize_utc`;
  optional timestamp policy remains at each field boundary.
- SHA-256 format validation is centralized as `domain/base.py::require_sha256`; models
  retain ownership of hash presence, generation, and content-matching rules.
- Storage implementation is complete.
- Dataset backend implementation is complete. Versioning, JSON/XLSX exchange, loading,
  export, atomic Dataset/Version persistence, and Dataset application workflows are
  implemented. All callers use `DatasetManagement`, and the obsolete top-level
  `case/` feature package has been removed without a compatibility alias.
- Run implementation planning is complete in `docs/run/implementation-plan.md`.
  `run/target_protocol.py` is implemented with the four-operation Case execution
  lifecycle. `run/manifest.py` was rejected as a forwarding layer because
  `domain.RunManifest` owns the complete contract. The next file checkpoint is
  `run/engine.py`.

## Global architecture decisions

- AgentGate remains one project. Do not create a separate repository for the evaluation harness.
- AgentGate is a complete Agent Evaluation Harness, not only an Eval Engine.
- AgentGate owns test execution, evaluation, regression, and analysis.
- `skill_analysis/` examines Agent/Skill definitions without executing them; `optimizer/`
  analyzes completed Runs, Results, and Traces. Do not merge these responsibilities.
- AgentGate does not build a full enterprise Control Plane or full observability platform.
- POC Control Plane and observability functions remain lightweight; production integrations should primarily use existing external systems.
- `domain/` is the single source of truth for domain models and domain invariants. Do not redefine `TestCase`, `Dataset`, `Run`, `Trace`, or similar objects in feature folders.
- External integrations are centralized under `integrations/`.
- Internal package name `control/` should not be confused with an enterprise Control Plane; the intended application orchestration layer is `application/`.

## `domain/` Level 2 result

Final structure:

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

The package is divided by stable business concepts rather than Web pages, database
tables, or workflow steps. Detailed responsibilities, estimated size, dependency rules,
versioning, secret handling, and test guidance are maintained in `docs/domain/README.md`.

Required P1 reconciliation:

- Split the inherited `domain/case.py`: individual Case models remain in `case.py`, while
  Dataset, DatasetVersion, and Dataset collection invariants move to `dataset.py`.
- Move `TargetSnapshot` from `run.py` into new `target.py` and adopt exact external Target
  references, descriptors, and immutable execution snapshots.
- Rename `evaluation.py` to `evaluator.py` to match its owned concept.
- Replace the inherited Run objects with immutable `RunManifest`, `EvaluationRun`,
  `RunStatus`, and legal lifecycle transitions.
- Add `artifact.py` for shared Artifact references and metadata.
- Add `skill_analysis.py` for persisted static Skill-analysis specifications, findings, reviews, and reports.
- Keep `report.py` as the composite domain read contract; report calculation remains in
  `result/report.py`.
- Do not create Agent or AgentVersion models because external customer platforms own
  those objects.

Confirmed rules:

- Domain model field validation belongs in `domain/`.
- Domain invariants belong in `domain/`.
- Dataset-level rules such as duplicate Case IDs belong in the Dataset domain model.
- Run status and legal state transitions belong in the Run domain model.
- Run configuration contains timeout, retry, target, and parallel execution settings.
- Per-Case status and retry-record models are deferred until real asynchronous progress or
  retry behavior requires them; retry details use Trace events.
- `RunManifest` is an immutable record of the versions and effective configuration used by one Run.
- Future execution-capacity concepts may include `TargetExecutionProfile`, but the exact domain structure remains to be reviewed.
- Domain Trace uses exact OTel Trace/Span IDs, extensible operation types, immutable JSON evidence, and no separate TraceTurn class.
- `EvaluationResult` directly owns `trace_id`; Check results own Span references and flattened failure location. Legacy Evidence and FailureObservation wrappers are removed.
- Evaluator error categories remain closed to crash, timeout, and invalid output; only LLM Judge results may own Judge call records.
- LLM Judge Evaluator configuration requires explicit model `provider_id` and `model_id`; `credential_ref` remains optional and opaque.

## `dataset/` Level 2 result

Final structure:

```text
dataset/
├── loader.py
├── export.py
├── versioning.py
├── sampling.py
├── generation/
└── formats/
```

Confirmed responsibilities:

- `loader.py`: load external test data and convert it into domain `Case` and `Dataset` objects.
- `export.py`: export domain Case/Dataset data to external formats. Renamed from `writer.py` because export is the actual business operation; low-level writing belongs in `formats/`.
- `versioning.py`: manage Case and Dataset revisions, hashes, change detection, and
  reproducibility metadata. Basic Run-to-asset lookup uses indexed storage references;
  broader graph lineage is deferred.
- `sampling.py`: select a reproducible subset of Cases using random, tagged, risk-stratified, failure-prioritized, smoke, regression, or full strategies. It does not execute Cases.
- `generation/`: reserved for a later research direction. P1 keeps the boundary but does not implement a complete synthetic-data system. Industry and technical research is required first.
- `formats/`: convert between external JSONL/YAML/CSV representations and domain objects. It does not perform domain validation, versioning, persistence, execution, or evaluation.

Removed:

- `writer.py`: renamed to `export.py`.
- `validation.py`: removed because format parsing belongs in `formats/`, field and invariant validation belongs in `domain/`, and external Tool/Policy/Evaluator availability checks belong in Run preflight.
- `models.py`: must not duplicate models already defined under `domain/`.
- `repository.py`: do not define a Case-specific repository. The shared persistence
  contract belongs in `storage/repository.py`, with implementations in `storage/`.

## `run/` Level 2 result

Final structure:

```text
run/
├── engine.py
├── process_manager.py
├── retry.py
├── artifacts.py
└── target_protocol.py
```

Confirmed responsibilities:

### `engine.py`

- Main Evaluation Harness execution engine.
- Executes one Case or a complete Dataset/Batch within one Run.
- Orchestrates Case execution and passes completed Agent executions to evaluation.
- Does not implement Agent-specific startup, evaluator rules, observability connectors, Web/API endpoints, or enterprise scheduling.
- A separate `runner.py` was rejected because Engine-versus-Runner was unclear and added an unnecessary forwarding layer.

### `process_manager.py`

- Renamed from `process_pool.py` because the implementation is not a traditional pool of persistent reusable workers.
- P1 execution model: one local Agent process per Session and per Case execution.
- Starts Agent processes, limits maximum parallel processes, records execution-to-PID/Workspace mapping, monitors processes and child processes, captures CPU/memory/runtime, handles normal/abnormal exits, terminates on timeout/cancel, collects exit status, and releases resources.
- When a process slot becomes available, it can start the next Case.
- Agent-specific commands and arguments come from the Target Adapter.

### `retry.py`

- Applies a Run `RetryPolicy` to infrastructure failures such as network errors, rate limits, temporary Agent API failures, and process crashes.
- Does not retry wrong answers, policy failures, or normal evaluation failures.
- Retry remains an execution function, not a domain class; each retry emits a Trace event.
- Coding Agent retries require a fresh Workspace so an earlier execution cannot contaminate the next.

### `artifacts.py`

- Collects and registers file-like execution outputs: code diffs, modified files, test reports, stdout/stderr, screenshots, coverage, and other generated files.
- Calculates metadata and hashes, then hands storage to the storage layer.
- Database records should generally hold Artifact references rather than large file contents.

### `target_protocol.py`

- Renamed from `target.py` to avoid confusion with the Target domain model.
- Defines the uniform internal execution protocol used by Engine.
- Minimal P1 operations: `start`, `get_status`, `wait`, and `cancel`.
- Each new Agent type needs a Target Adapter under `integrations/targets/` that translates its CLI, Python, or HTTP behavior into this protocol.
- Examples: `mscli.py`, `mini_swe.py`, `http_agent.py`, and `dify.py`.
- Engine depends only on the protocol. A local Target Adapter uses `process_manager.py`; a remote Target Adapter calls an external Agent API.

Removed:

- `runner.py`: duplicates Engine execution responsibility.
- `scheduler.py`: scheduling does not belong in `run/`; local, Celery, and customer
  background job dispatch implementations belong under
  `integrations/job_dispatchers/` and invoke the same application/Run execution boundary.
- `concurrency.py`: concurrency is not an independent business module.
- `process_pool.py`: renamed to `process_manager.py`.
- `lifecycle.py`: legal Run status transitions belong in `domain/`.
- `timeout.py`: timeout configuration belongs in domain RunConfig; Engine waits; ProcessManager or Target Adapter performs cancellation/termination.
- `context.py` / `execution_context.py` / `run_env.py`: proposed object mixed manifest configuration, domain IDs, and runtime handles. P1 keeps PID/Workspace/runtime handles inside ProcessManager.
- `events.py`: proposed events duplicated domain state changes. P1 does not introduce an Event Bus for ordinary status changes.
- `manifest.py`: rejected because `domain.RunManifest` already owns immutable exact
  references, execution configuration, validation, and hashing. Application Run
  management constructs it after resolving assets; a Run-layer builder would only
  forward arguments.
- `snapshot.py`: empty obsolete scaffold removed with no replacement module.

### Local Agent parallel execution decision

- Most interactive/local Agents such as Claude Code, mscli, and mini-swe are effectively single-concurrency per execution instance/session.
- Parallel evaluation means starting multiple isolated Agent instances, not making one Agent Loop process multiple user tasks.
- P1 uses multiple processes, one Session and one isolated Workspace per process.
- A Session is a logical state, not the same concept as an OS process; however the P1 local execution mapping is intentionally one Session per Agent process.
- Cloud Agents can run multiple Sessions only if their API/runtime exposes independent Session/Run creation and supports concurrent execution.
- AgentGate cannot manufacture internal parallelism for a remote service that only exposes one serial Session.
- mscli remains a local single-Session harness. AgentGate may start multiple mscli instances through a Target Adapter; mscli should not be turned into a cloud multi-Session platform for this purpose.

### Capacity and profiling decision

- Do not calculate parallelism as one Agent per CPU core.
- Agent subprocesses may invoke compilers, tests, package managers, and other tools that consume multiple CPU cores, memory, I/O, and process slots.
- Profile representative `Agent type + Workload type + Toolchain` combinations.
- Record average/peak CPU, average/peak memory, disk/I/O, child process count, runtime, model-wait ratio, failures, and timeouts.
- Use the resource bottleneck plus headroom to recommend `max_parallel_runs`, then calibrate with stepped throughput tests.
- P1 uses a fixed recommended `max_parallel_runs`; adaptive concurrency and automatic capacity recommendations are later capabilities.
- Local CLI Agents usually do not enforce CPU limits themselves. Cloud/Sandbox execution generally enforces limits through containers, cgroups, or Kubernetes.

## `trace/` Level 2 result

Final structure:

```text
trace/
├── normalizer.py
└── redaction.py
```

Confirmed responsibilities:

- `normalizer.py`: convert varying OTel/OpenInference/LoongSuite GenAI attributes into AgentGate's unified domain Trace objects. OTel remains the external interchange/transport standard.
- `redaction.py`: remove or mask personal data, credentials, financial data, sensitive Tool arguments/results, code secrets, and other protected content before Judge use, UI display, dataset generation, reporting, or external writeback.

Design decisions:

- Do not invent a competing proprietary Trace wire format.
- OTel standardizes trace/span structure but does not guarantee identical Agent semantic attributes across every platform; normalization is still required.
- The internal domain representation can expose normalized `AgentStep`, `LLMCall`, `ToolCall`, `Retrieval`, `Approval`, `StateChange`, and Error semantics while retaining original trace/span IDs.

Removed/deferred:

- `graph.py`: P1 uses OTel parent-child Span relationships. Add `execution_graph.py` later only when complex multi-Agent, causal, state-transition, or trajectory analysis requires it.
- `collector.py`: AgentGate should consume traces produced by the Agent or existing observability platform, not build another full collector. A lightweight POC OTLP receiver, if required, belongs in `integrations/observability/otlp_http_receiver.py`.
- `correlation.py`: Target Adapter obtains or returns `trace_id`; observability integration fetches the trace. Add a separate correlator only for future complex cross-trace merging.
- `evidence.py`: each Evaluator knows what evidence it needs and returns evidence span references in its EvaluationResult. Trace should not guess evaluator-specific evidence.
- `repository.py`: do not define a Trace-specific repository. The shared persistence
  contract belongs in `storage/repository.py`; external traces can remain referenced
  in observability platforms.

## `evaluator/` Level 2 result

Final structure:

```text
evaluator/
├── evaluator_protocol.py
├── executor.py
├── models.py
├── hybrid.py
├── rule/
└── judge/
```

Confirmed responsibilities:

### `evaluator_protocol.py`

- Renamed from `base.py`.
- Defines the unified Evaluator contract.
- All evaluator implementations consume a common evaluation input and return a common result containing score, outcome, reason, and Trace Span references.

### `executor.py`

- Renamed from `engine.py` to avoid confusion with `run/engine.py`.
- Receives a completed Case plus normalized Trace/Artifact references and executes all Evaluators already selected by the RunManifest/application composition.
- Builds evaluator inputs, invokes evaluators, captures evaluator execution errors/timeouts and execution metadata, and returns independent EvaluationResults.
- Does not run the target Agent, choose evaluator policy, implement evaluator rules, aggregate Run scores, make a release-gate decision, or persist data directly.

### `models.py`

- Contains runtime-only, non-persisted evaluation inputs, dependency state, candidates,
  and execution errors shared by evaluator execution.
- Persistent Evaluator specifications and Results remain in `domain/`.

### `hybrid.py`

- Existing module retained.
- Combines deterministic rule evaluation and LLM Judge evaluation where required.
- Replaces the proposed generic `composite.py`.

### `rule/`

- Contains deterministic evaluators for Tool requirements/prohibitions, Tool arguments, final state, format, budget, policy, and deterministic trajectory/path checks.
- Fast, repeatable, and token-free.

### `judge/`

- Contains LLM-based semantic/subjective evaluation.
- Used for correctness, completeness, business-semantic compliance, reasoning quality, user-intent completion, and other judgments that cannot be fully expressed as fixed rules.
- Model access is provided through `integrations/model_providers/`.

Removed:

- `registry.py`: P1 does not implement startup registration or a dynamic evaluator plugin registry.
- `factory.py`: explicitly rejected. P1 evaluator objects are directly composed by application code and passed to the executor.
- `composite.py`: duplicates existing `hybrid.py`.
- `trajectory/`: trajectory is what is evaluated, while Rule/Judge/Hybrid are evaluation methods. Deterministic trajectory evaluation belongs under `rule/`; semantic trajectory evaluation belongs under `judge/` or `hybrid.py`.
- `safety/`: safety is also an evaluation subject/dimension, not a sibling evaluation mechanism. Deterministic safety checks belong under `rule/`; semantic safety checks belong under `judge/` or `hybrid.py`.

## `result/` Level 2 result

Final structure:

```text
result/
├── metrics.py
├── gate.py
├── report.py
└── comparison.py
```

Confirmed responsibilities:

- `metrics.py`: calculate and aggregate primary Result summaries by metric, quality
  dimension, evaluator kind, and overall score. It implements the exact `MetricPlan`
  identified in the Run manifest and rejects unsupported plan versions or one metric key
  assigned to multiple dimensions. Metric summaries contain machine keys; display labels
  belong to the presentation layer. The inherited `calc_metrics.py` name is removed.
- `gate.py`: gather primary Result facts, consume the overall Metric score, and apply the
  snapshotted release-gate specification. Gate decisions contain a typed reason code and
  missing-result references; Result counts remain in Metrics. Metrics do not expose a
  separate `incomplete` flag because errors and missing Results already have distinct,
  queryable representations.
- `report.py`: assemble one validated report from a completed Run, Results, Metrics, and
  release-gate decision. Trace references remain on Results; Artifact linkage is added only
  when a real Artifact producer requires it. The implemented P1 behavior in `service.py`
  moves here because building a report is its actual responsibility.
- `comparison.py`: compare completed Runs for regression, Agent/model/Prompt version
  differences, newly passed or failed Cases, metric differences, and Gate changes. It is a
  general Result capability and is not limited to A/B testing.

Dependency direction:

```text
Evaluation Results -> metrics.py -> gate.py -> report.py
                         |
                         +-------> comparison.py <--- another Run
```

Rules:

- Metrics answer how one Run performed.
- Gate answers whether one Run met configured thresholds and fails closed for missing,
  errored, blocking, review-required, or wholly inapplicable results. Individual
  not-applicable Results do not block an otherwise measurable Run.
- Report packages one Run's conclusion.
- Comparison answers what changed between Runs.
- Comparison does not own experimental design, statistical significance, or winner
  selection.
- Result modules do not persist data, execute Evaluators, collect Traces, or implement Web
  visualization.

Removed/moved:

- `calc_metrics.py`: renamed to `metrics.py`; do not add a duplicate `aggregation.py`.
- `service.py`: renamed to `report.py`; broader application orchestration belongs in
  `application/`.
- `export/`: removed from the Result core. JSON/JUnit/Markdown/callback output adapters
  belong under `integrations/result_outputs/`. FastAPI JSON output is sufficient for the POC.

## `skill_analysis/` Level 2 result

Static Skill analysis is part of the Agent evaluation product, but it does not execute
Cases and must not emit fake dynamic evaluation Results.

Final structure:

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

Confirmed responsibilities:

- `analyzer_protocol.py`: define the common contract for static analyzers.
- `models.py`: hold non-persisted analyzer inputs, candidates, features, and errors.
- `description_quality.py`: check whether Skill descriptions are clear, complete, and
  routable.
- `skill_relationships.py`: detect overlap, conflict, and confusion among Skill
  definitions.
- `prompt_alignment.py`: check Agent Prompt, Skill Prompt, description, Tool, and
  capability alignment.
- `llm_semantic.py`: perform bounded LLM-assisted semantic checks through an injected
  model-provider boundary.
- `pipeline.py`: run explicitly composed analyzers, merge findings, and construct the
  static risk matrix.

Ownership rules:

- Persisted `SkillAnalysisSpec`, findings, reviews, and `SkillAnalysisReport` objects belong in
  `domain/skill_analysis.py`.
- Target resolution, invocation, persistence, and finding-review workflows belong in
  `application/skill_analysis.py`.
- HTTP endpoints belong in `server/routes/skill_analysis.py`.
- The Web UI may present static and dynamic evaluation under one product navigation area.
- A static risk matrix estimates definition risk; an observed confusion matrix requires
  executed Cases and remains in `optimizer/`.
- Static analysis never edits external Agent or Skill definitions automatically.

Removed from the pre-refactor plan:

- `base.py` becomes the explicitly named `analyzer_protocol.py`.
- `registry.py` is removed; application composition selects supported analyzers.
- `service.py` is removed; use-case orchestration belongs in `application/`.
- Separate `normalization.py`, `merge.py`, and `matrix.py` are not created initially;
  extract them only when implementation complexity justifies independent modules.

Estimated implementation size is 600-900 production lines, excluding persisted domain
contracts and tests. Detailed behavior and acceptance criteria remain in
`docs/history/planning-v1/skill-static-analysis-plan.md`.

## `optimizer/` Level 2 status

The top-level capability is retained because Badcase clustering, confusion analysis,
root-cause hypotheses, and reviewable suggestions are product requirements. It is the last
planned feature and will receive a detailed review when implementation begins.

Current P1 files are docstring-only scaffolds:

```text
optimizer/
├── clustering.py
├── root_cause.py
└── suggestions.py
```

Decisions already confirmed:

- Optimizer consumes failed Results and Trace evidence.
- Suggestions require human review and never mutate external Agent assets automatically.
- `optimizer/service.py` is removed. Loading data, saving analysis, recording review, and
  starting regression are workflows owned by `application/optimization_service.py`.
- If the three analysis steps later need one internal entry point, use
  `optimizer/pipeline.py`, not a generic `service.py`.

## Removed or deferred top-level product packages

### `experiment/`

Remove `experiment/` from `refactor-1`. The P1 package contains only docstrings and no
runtime behavior. Generic Run/version/regression comparison belongs in
`result/comparison.py`.

If controlled A/B testing becomes a concrete requirement, introduce a narrowly named
`ab_test/` capability later for experiment design, paired statistics, and winner decisions.
Do not keep an empty broad `experiment/` package.

### `lineage/`

Do not create a top-level `lineage/` package in `refactor-1`. Basic reproducibility and
lineage remain required, but they are provided by immutable Run data and indexed database
relationships:

```text
RunManifest
├── Target/Agent/Skill version
├── Dataset version and content hash
├── Evaluator versions and hashes
├── Prompt/model/tool versions
└── effective Run configuration

run_asset_refs
├── run_id
├── asset_type
├── asset_id
├── asset_version
└── content_hash
```

Ownership:

- `domain/`: RunManifest and versioned asset references;
- `storage/`: persist indexed references and query Runs by asset;
- `application/lineage_queries.py`: expose queries such as "Which Runs used Dataset version 3?";
- `server/`: expose the query API.

Add a full `lineage/` package later only for multi-hop graph traversal, dependency impact
analysis, or graph visualization.

### `queue/`

Do not create a top-level `queue/` package in `refactor-1`. The P1 package contains only
empty contracts and no working queue implementation.

Execution modes use replaceable adapters:

```text
Standalone synchronous POC -> direct application execution
Asynchronous demo          -> Celery job dispatcher + Redis
Customer environment       -> external scheduler calls AgentGate internal execution API
                             -> shared application execution boundary
```

Celery integration belongs under `integrations/job_dispatchers/celery.py`, not in the
Run engine or a Queue domain package.

Rules:

- AgentGate storage owns Run status and Results.
- Celery task status is operational information only.
- Store the Celery task ID as an external execution reference.
- Celery retries infrastructure failures, not Agent quality failures.
- Submission is idempotent.
- Redis/Celery result storage is never the authoritative AgentGate Result store.
- Every scheduler adapter invokes the same application/Run execution boundary.

## External integration Notes

Confirmed integration structure so far:

```text
integrations/
├── targets/
├── observability/
├── model_providers/
├── result_outputs/       deferred until an external output is implemented
└── job_dispatchers/       Celery background execution
```

### `integrations/targets/`

- Implements the internal Target Protocol defined by `run/target_protocol.py`.
- Confirmed adapters are `http_agent.py`, `process_agent.py`,
  `python_function.py`, and `trace_replay.py`.
- Do not add another `base.py`; the protocol already belongs to `run/`.
- `process_agent.py` understands Agent commands and outputs, while
  `run/process_manager.py` owns PID, resource, timeout, cancellation, and process
  cleanup behavior.
- `python_function.py` is primarily for demos and tests because in-process Agent
  failures can affect the worker.
- `trace_replay.py` evaluates an existing execution without invoking an Agent.
- The generic remote-Agent adapter is named `integrations/targets/http_agent.py`,
  not `http.py`. Its responsibility is to translate the Target Protocol into a
  configurable HTTP Agent invocation, wait for the terminal HTTP/SSE response,
  and normalize it into AgentGate execution output. The name `http.py` is
  rejected because it is easily confused with a low-level HTTP transport module
  or Python's `http` package.
- Platform-specific behavior that cannot be expressed by the generic HTTP Agent
  contract belongs in adapters such as `integrations/targets/dify.py` and
  `integrations/targets/coze.py`; they may share a private HTTP transport helper.

### `integrations/observability/`

- Owns transport and vendor-specific trace ingestion or retrieval, not trace
  interpretation, evaluation, storage, or dashboards.
- POC contains `otlp_http_receiver.py`, moved from
  `trace/receivers/otlp_http.py`; it accepts and decodes OTLP/HTTP, then delegates
  semantic conversion to `trace/normalizer.py`.
- Langfuse, Phoenix, LangSmith, and LoongSuite connectors are added only when a
  real integration is implemented. Do not create empty modules in `refactor-1`.

### `integrations/model_providers/`

- Renamed from `integrations/models/` because `models` is ambiguous with domain,
  Pydantic, and persistence models.
- POC contains only `openai_compatible.py` for Judge model access.
- Evaluator prompt construction and response interpretation remain in
  `evaluator/judge/`; application composition selects the provider and a
  credential reference.
- Run data records `credential_ref`, never a secret. Environment variables are
  sufficient for POC secret resolution; production may use an external secret
  service.

### `integrations/result_outputs/`

- Renamed from `integrations/sinks/` because `sinks` is unclear infrastructure
  jargon.
- Reserved for external delivery such as JUnit, Markdown, and webhook outputs.
- FastAPI responses belong in `server/`, UI rendering in `web/`, result
  calculation in `result/`, and persistence in `storage/`.
- Do not create this folder in `refactor-1` until an external result output is
  implemented.

### `integrations/job_dispatchers/`

- Renamed from `integrations/schedulers/` because the POC responsibility is
  background job submission, not deciding a business schedule.
- POC contains only `celery.py`.
- `celery.py` submits a `run_id`, registers the worker task, calls the shared
  application execution boundary, stores the Celery task ID as an external
  execution reference, and supports infrastructure retry and best-effort
  cancellation.
- AgentGate storage remains authoritative for Run status and Results. Celery and
  Redis state is operational only.
- Synchronous mode calls the application execution boundary directly.
- A customer-owned scheduler normally calls AgentGate through an inbound internal
  execution API. Add an outbound customer dispatcher only if AgentGate must submit
  work into that scheduler.
- Prefer existing OTel, LoongSuite, Langfuse, Phoenix, enterprise schedulers, and enterprise Control Plane systems.
- AgentGate may include lightweight POC integrations but should not rebuild those platforms.

## `application/` Level 2 progress

The application layer coordinates complete AgentGate use cases between transport
entry points and the core capabilities. It does not own HTTP schemas, domain
invariants, Agent execution mechanics, evaluator algorithms, SQL, or vendor-specific
integration behavior.

Planned capability-oriented modules are:

```text
application/
├── run_management.py
├── dataset_management.py
├── dataset_generation.py      future
├── target_catalog.py
├── evaluator_management.py
├── result_reader.py
├── skill_analysis.py
└── lineage_queries.py
```

### `application/dataset_management.py`

- Coordinates user-facing Dataset and Case lifecycle operations: Dataset create,
  update, archive, copy, version listing, draft create/publish/discard,
  import/export, and Case add/update/delete/copy/reorder.
- Delegates invariants to `domain/`, import/export mechanics to `dataset/loader.py`
  and `dataset/export.py`, revisions and hashes to `dataset/versioning.py`, format
  conversion to `dataset/formats/`, and persistence to the storage interface.
- The orchestration formerly owned by `case.DatasetService` is implemented here;
  reusable Dataset mechanics remain in `dataset/`.
- Does not generate synthetic Cases, execute Datasets, implement formats, define
  domain models, calculate hashes, write SQL, or expose HTTP.
- Automatic generation is a separate future application use case in
  `application/dataset_generation.py`. It coordinates Target metadata,
  `dataset/generation/`, a model provider, and creation of a Dataset draft, then
  delegates persistence to Dataset management.

### `application/target_catalog.py`

- Provides read-only discovery and resolution for externally owned Agent and Skill
  Targets.
- Selects the appropriate platform adapter, applies application access/filtering
  rules, lists Targets and versions, resolves an exact `TargetRef`, and returns
  normalized `TargetDescriptor` objects.
- Serves Run management, Dataset generation, and static Skill analysis.
- Vendor URL, authentication, and response handling remain in
  `integrations/targets/`; Target identity and descriptor models remain in
  `domain/target.py`.
- Does not create or edit external Targets, invoke them, generate Cases, perform
  static analysis, store plaintext credentials, or build a RunManifest.
- Execution must not silently resolve a mutable `latest` alias. When a platform
  cannot expose a stable version ID, record the published deployment identity and
  descriptor/configuration hash and make the reproducibility limitation explicit.

### `application/evaluator_management.py`

- Used instead of `evaluator_catalog.py`: Targets are externally owned and read
  through a catalog, while Evaluators are AgentGate-owned definitions that require
  management.
- Coordinates supported evaluator types, definition creation/update, immutable
  version creation, configuration validation, publish/disable operations, and
  exact-version resolution for RunManifest construction.
- Rule configuration may include JSON structure and field-value constraints; LLM
  Judge configuration records criteria, provider, model, `credential_ref`, and
  generation settings.
- Delegates domain invariants to `domain/evaluator.py`, execution to
  `evaluator/executor.py`, implementation logic to `evaluator/rule/` and
  `evaluator/judge/`, model calls to `integrations/model_providers/`, aggregate
  calculation to `result/`, and persistence to the storage interface.
- Does not reintroduce a dynamic plugin registry. Application composition
  explicitly maps supported evaluator types to implementations.
- Published Evaluator versions are immutable and identify rule/Judge criteria,
  model configuration, and evaluator implementation version.

### `application/skill_analysis.py`

- Coordinates static Skill-evaluation use cases for Agent creation checks and evaluation
  preparation.
- Resolves an exact TargetDescriptor through `target_catalog.py`, invokes the
  `skill_analysis/pipeline.py` capability, persists immutable reports, and records human
  finding reviews separately.
- May select an LLM model provider and opaque credential reference for semantic checks.
- Does not execute Cases, create dynamic evaluator Results, implement analyzer algorithms,
  edit external Skills, write SQL, or expose HTTP.
- Static findings do not block a Run unless an explicit application policy says so.

### `application/result_reader.py`

- Provides the read-only application boundary for Run reports, Case results,
  Badcases, Trace details, Artifact references, and dashboard overview summaries
  used by Web, CLI, and APIs.
- Loads and combines canonical stored data through repository interfaces and
  delegates canonical report construction to `result/report.py`.
- May retrieve an externally stored Trace through an observability adapter, then
  normalize and redact it before returning application data.
- Does not calculate scores or metrics, modify Cases or Runs, implement SQL,
  serialize HTTP, or render charts.
- Case updates initiated from a Result page are delegated to
  `dataset_management.py`.
- Keep this module initially. Remove it later if implementation proves it is only
  a one-call repository forwarding layer.
- Do not create `application/overview.py` in `refactor-1`. Dashboard totals,
  running/completed counts, recent Runs, and latest summary data remain read
  operations in `result_reader.py`. Split them later only if dashboard analytics
  develops substantial independent complexity.

### `application/lineage_queries.py`

- Provides read-only version relationship and usage-history queries for
  reproducibility, audit, regression, and impact inspection.
- Reads immutable asset references recorded by `RunManifest` and indexed by
  storage, including Target, Dataset, Evaluator, Prompt, model, Tool, and effective
  configuration versions or hashes.
- Answers both directions: which exact assets a Run used, and which Runs used one
  exact asset version.
- Does not write lineage independently, construct Run manifests, implement SQL, or
  build a graph database.
- The top-level `lineage/` scaffold is removed in `refactor-1`. Add a dedicated
  lineage capability later only for multi-hop graph traversal, dependency impact
  analysis, or graph visualization.

### `application/run_management.py`

- Owns the complete Run lifecycle use case: Run creation, submission,
  cancellation, and the shared worker-side execution entry point.
- Resolves selected Dataset, Target, and Evaluator versions, delegates immutable
  manifest construction to `domain.RunManifest`, persists the Run, and selects
  synchronous or configured background dispatch.
- Coordinates legal domain Run status transitions and persistence around
  `run/engine.py`.
- Provides the same execution boundary to Celery and an external control plane.
- Does not execute individual Cases, manage OS processes, invoke external Agents,
  calculate scores, implement Celery, define domain status rules, or expose HTTP.
- P1 keeps submission and worker-side execution in one module. Split them only if
  the module develops substantial independent complexity.

## `storage/` Level 2 progress

Confirmed `refactor-1` structure:

```text
storage/
├── __init__.py
├── repository.py
├── sqlite.py
└── artifacts.py
```

This is three functional modules and four Python files including `__init__.py`.

### `repository.py`

- Renamed from `base.py` because the file defines the persistence repository
  contract rather than a general base class.
- Initially contains one `AgentGateRepository` protocol for object-level
  persistence operations used by application and core capabilities.
- Keeps SQL and database-specific behavior out of application code.
- A test or future PostgreSQL implementation can satisfy the same contract.
- Split into capability-specific repository protocols only when the combined
  contract develops real independent complexity.

### `artifacts.py`

- Stores and retrieves file-like or large Agent execution outputs such as code
  diffs, generated documents, test reports, screenshots, and stdout/stderr.
- `run/artifacts.py` discovers outputs, calculates hashes, and creates Artifact
  metadata; `storage/artifacts.py` stores and retrieves the actual bytes.
- POC uses a local Artifact directory. S3, MinIO, or customer object-storage
  adapters are deferred.
- Database records hold Artifact identity, media type, size, checksum, and storage
  location rather than large file contents.

Rules:

- SQLite/PostgreSQL is authoritative for AgentGate Runs and Results; Redis/Celery
  state is operational only.
- Storage does not define domain invariants, execute Runs or Evaluators, calculate
  metrics, expose HTTP, or format UI responses.
- `postgres.py`, `migrations/`, and object-storage-specific modules are added
  only when those capabilities are implemented.

### `sqlite.py`

- Implements the `AgentGateRepository` contract with SQLite.
- Owns connection handling, POC schema initialization, transactions, canonical
  domain-object JSON serialization/deserialization, SQL queries, constraints, and
  indexes.
- Uses selected relational columns for identity, filtering, ordering, and indexes,
  while retaining complete immutable domain objects as canonical JSON payloads.
- Likely persisted areas include Datasets and versions, Runs,
  Traces, Results, Evaluator versions, Run asset references, and Artifact metadata;
  the exact schema is finalized during the domain audit.
- Application/domain code decides whether an operation such as Dataset publishing
  is valid and constructs the intended domain change; SQLite guarantees the
  related writes are atomic.
- For the Celery-backed POC, enable foreign keys, WAL mode, a bounded busy timeout,
  and short transactions. Move to PostgreSQL when write concurrency or volume
  exceeds the POC profile.
- Demo Agent business state is not AgentGate persistence. Move the current
  `business_state` table and methods into the Demo/example implementation.
- Does not define lifecycle rules, construct Dataset versions, execute Agents or
  Evaluators, calculate metrics, or return Web-specific data.

## `cli/` Level 2 result

Final `refactor-1` structure:

```text
cli/
├── __init__.py
├── main.py
├── run_commands.py
├── dataset_commands.py
└── result_commands.py
```

This is four functional modules and five Python files including `__init__.py`.

Confirmed responsibilities:

- `main.py`: assemble the Typer root application, register command groups, load
  CLI configuration, and wire application services. It does not implement use
  cases.
- `run_commands.py`: expose Run start/list/status/cancel commands through
  `application/run_management.py`.
- `dataset_commands.py`: expose Dataset list/import/export/publish operations
  through `application/dataset_management.py`.
- `result_commands.py`: expose report, Badcase, and Trace reads through
  `application/result_reader.py`, and map Gate conclusions to documented CI exit
  codes.
- CLI parses arguments, presents output, and maps errors/exit codes. It does not
  execute Cases, query SQLite directly, calculate metrics, invoke external Agents,
  or duplicate HTTP/API logic.
- Remove the current `cli/application.py` because the name conflicts with the
  top-level application layer and its direct repository access bypasses that
  boundary.
- Remove the generic empty `cli/commands.py`; command ownership is explicit in
  the three command-group modules.
- Add Target, Evaluator, lineage, or shared formatting modules only when those
  command groups develop real behavior.

## `server/` Level 2 result

FastAPI remains the AgentGate HTTP server because it matches the existing Python and
Pydantic stack, provides request validation and OpenAPI, supports REST and streaming,
and is already working in P1.

Final `refactor-1` structure:

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

Confirmed responsibilities:

- `app.py`: application factory, lifespan, middleware, CORS, exception-handler
  registration, and router registration.
- `dependencies.py`: FastAPI dependency providers for configured application
  services and request-level authentication context. No external DI library is
  required for the POC.
- `errors.py`: map typed application errors to HTTP status and response shapes;
  do not infer error types from message strings.
- `routes/system.py`: health and readiness endpoints.
- `routes/runs.py`: Run submission, list/status/cancel/progress endpoints through
  Run management and Result reader application boundaries.
- `routes/datasets.py`: Dataset/Case lifecycle, import/export, draft, and publish
  endpoints through Dataset management.
- `routes/catalogs.py`: Target discovery and Evaluator management endpoints.
  Split later only if either API develops substantial size.
- `routes/results.py`: reports, Case results, Badcases, Trace/Artifact detail,
  dashboard summaries, and lineage query endpoints.
- `routes/telemetry.py`: register OTLP/HTTP ingestion and delegate protocol
  handling to `integrations/observability/otlp_http_receiver.py`.
- `routes/skill_analysis.py`: expose static Skill-analysis submission, report retrieval,
  and finding-review endpoints through `application/skill_analysis.py`.
- Keep small HTTP request/response schemas in the owning route module. Add a
  separate schemas package only when schemas are genuinely shared or numerous.
- Long evaluations never run in the request process. Run submission persists a
  queued Run, dispatches background work, and normally returns HTTP 202.
- Add a separate internal-execution route module only when external customer
  control-plane integration is implemented.
- Remove the current broad `server/application.py` after splitting it. Remove
  empty generic `server/routes.py` and `server/services.py`; business services
  belong in `application/`.
- Server does not query SQLite directly, execute Agents/Evaluators, construct
  manifests, calculate metrics, or contain customer scheduler logic.

## `web/` Level 2 result

Frontend stack:

- Vue 3 and TypeScript;
- Vite;
- Element Plus;
- Vue Router;
- Playwright for desktop and mobile workflows.

Target structure:

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

Active POC pages and routes:

```text
/                 OverviewPage
/runs             RunWorkspacePage
/results          ResultCenterPage
/results/:runId   ResultDetailPage
/datasets         DatasetWorkspacePage
/evaluators       EvaluatorWorkspacePage
/skill-analysis   SkillAnalysisPage
/optimizer        OptimizerPage          future
```

Confirmed responsibilities:

- `App.vue` mounts the application layout and router view; it owns no evaluation
  workflow state.
- `router/` maps URLs to pages and replaces manual `history.pushState` navigation.
- `layouts/` owns the sidebar, header, responsive navigation, and page frame.
- `pages/` coordinates one complete user workflow per route.
- `components/` contains reusable controls grouped by shared, Run, Result, Dataset, and
  Skill-analysis concerns.
- `composables/` owns reusable stateful client workflows such as Run progress and
  Dataset workspace state.
- `api/` contains shared HTTP transport and capability-specific endpoint modules.
- `types/` contains frontend API contracts without duplicating backend invariants.
- `styles/` contains design tokens and global base styles; feature styles remain scoped
  where practical.
- Seven pages are active for the POC. Optimization Center is the eighth, deferred page.
- Trace inspection remains part of Result Detail rather than a separate primary page.
- Page-local state and composables are sufficient initially; add Pinia only for proven
  cross-route mutable state.
- Preserve the inherited Chinese UI, typed Dataset components, responsive sidebar, and
  desktop/mobile Playwright behavior during refactor.
- Existing uncommitted Web changes are user-owned baseline work and are not included in
  architecture-documentation commits.
- Detailed rules are maintained in `docs/web/README.md`.

## Review completion

Level 1 and Level 2 are complete. Level 3 is intentionally deferred to implementation
review. The authoritative target architecture is `docs/architecture.md`.
