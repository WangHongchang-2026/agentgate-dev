# AgentGate Architecture Review Ledger

Last updated: 2026-08-23

## Review baseline and reconciliation status

The source of truth is the Git branch `goal/p1-demo`, not `main` and not the earlier conceptual directory proposal.

The Level 2 first-pass reviews for `case/`, `run/`, `trace/`, and `evaluator/` are
complete and remain useful architecture decisions. They are not discarded. Specific
keep/delete/rename decisions that conflict with working `goal/p1-demo` behavior must be
revalidated before implementation on `refactor-1`.

Confirmed mismatches requiring re-review include:

- `case/validation.py` has a real publish-time whole-Dataset validation role; the earlier deletion decision is withdrawn pending re-review.
- `evaluator/registry.py` is implemented and resolves evaluator/operator implementations and versions; the earlier deletion decision is withdrawn pending re-review.
- `evaluator/runner.py` is implemented with per-turn evaluation, dependency resolution, memoization, and error Results; the earlier replacement decision is withdrawn pending re-review.
- `evaluator/models.py` contains runtime-only, non-persisted evaluation models; the earlier blanket assumption that all models belong in `domain/` was incorrect.
- `trace/receivers/otlp_http.py` is an implemented lightweight OTLP ingestion boundary; it must be assessed separately from building a full observability collector.
- `run/core.py` currently contains the working P1 RunEngine, Target protocol, scheduler adapter, and Python function target; the empty scaffold files cannot be reviewed independently of this implementation.
- `result/` on `goal/p1-demo` contains implemented `calc_metrics.py`, `gate.py`, and `service.py`; it does not contain `verdict.py`.

Current review status:

- Level 1: confirmed.
- Level 2 first-pass: `case/`, `run/`, `trace/`, `evaluator/`, and `result/` completed.
- `optimizer/`: retained as a future feature boundary; detailed design is deferred until
  implementation.
- `experiment/`, `lineage/`, and `queue/`: removed as top-level `refactor-1` packages for
  the reasons recorded below.
- Targeted P1 reconciliation remains required for the mismatches listed above.
- No implementation refactor begins until the review is consolidated and the
  `refactor-1` branch is created.

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
2. `case/`
3. `run/`
4. `trace/`
5. `evaluator/`
6. `result/`
7. `analysis/`
8. `optimizer/`
9. `integrations/`
10. `application/`
11. `storage/`
12. `cli/`
13. `server/`

`web/` is a separate frontend directory and is not included in the 13 backend folders.

Current Level 2 progress:

- `case/`: completed.
- `run/`: completed.
- `trace/`: completed.
- `evaluator/`: completed.
- `result/`: completed.
- `analysis/`: retained as a top-level static Agent/Skill definition-analysis capability;
  detailed Level 2 review is pending.
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
- Current next folder: `server/`.
- `domain/` exists in the user's implementation but its Level 2 contents have not yet been reviewed.

## Global architecture decisions

- AgentGate remains one project. Do not create a separate repository for the evaluation harness.
- AgentGate is a complete Agent Evaluation Harness, not only an Eval Engine.
- AgentGate owns test execution, evaluation, regression, and analysis.
- `analysis/` examines Agent/Skill definitions without executing them; `optimizer/`
  analyzes completed Runs, Results, and Traces. Do not merge these responsibilities.
- AgentGate does not build a full enterprise Control Plane or full observability platform.
- POC Control Plane and observability functions remain lightweight; production integrations should primarily use existing external systems.
- `domain/` is the single source of truth for domain models and domain invariants. Do not redefine `TestCase`, `Dataset`, `Run`, `Trace`, or similar objects in feature folders.
- External integrations are centralized under `integrations/`.
- Internal package name `control/` should not be confused with an enterprise Control Plane; the intended application orchestration layer is `application/`.

## `domain/` cross-module Notes

- Domain model field validation belongs in `domain/`.
- Domain invariants belong in `domain/`.
- Dataset-level rules such as duplicate Case IDs belong in the Dataset domain model.
- Run status and legal state transitions belong in the Run domain model.
- Run configuration contains timeout, retry, target, and parallel execution settings.
- Attempt/CaseRun models carry IDs, execution status, and `trace_id` references.
- `RunManifest` is an immutable record of the versions and effective configuration used by one Run.
- Future execution-capacity concepts may include `TargetExecutionProfile`, but the exact domain structure remains to be reviewed.

## `case/` Level 2 result

Final structure:

```text
case/
├── loader.py
├── export.py
├── versioning.py
├── sampling.py
├── generation/
└── formats/
```

Confirmed responsibilities:

- `loader.py`: load external test data and convert it into domain `TestCase` and `Dataset` objects.
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
├── manifest.py
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
- P1 execution model: one local Agent process per Session and per Case Attempt.
- Starts Agent processes, limits maximum parallel processes, records Attempt-to-PID/Workspace mapping, monitors processes and child processes, captures CPU/memory/runtime, handles normal/abnormal exits, terminates on timeout/cancel, collects exit status, and releases resources.
- When a process slot becomes available, it can start the next Case.
- Agent-specific commands and arguments come from the Target Adapter.

### `retry.py`

- Applies a Run `RetryPolicy` to infrastructure failures such as network errors, rate limits, temporary Agent API failures, and process crashes.
- Does not retry wrong answers, policy failures, or normal evaluation failures.
- One CaseRun may contain multiple Attempts.
- Coding Agent retry requires a fresh Workspace so the first Attempt cannot contaminate the second.

### `manifest.py`

- Renamed from `snapshot.py`/`snapshot_builder.py` to avoid confusion with before/after state snapshots.
- Resolves vague Run requests into immutable, version-specific execution manifests.
- Locks Dataset, Case, Agent, model, Prompt, Tool/Skill, Evaluator, Target, and effective RunConfig versions/hashes.
- Used for reproducibility, audit, and version provenance.
- Does not execute Agents, calculate scores, collect outputs, or write directly to a database.

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
- `context.py` / `execution_context.py` / `run_env.py`: proposed object mixed RunConfig, RunSnapshot, domain IDs, and runtime handles. P1 keeps PID/Workspace/runtime handles inside ProcessManager.
- `events.py`: proposed events duplicated domain state changes. P1 does not introduce an Event Bus for ordinary status changes.

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
- `correlation.py`: Attempt stores `trace_id`; Target Adapter obtains or returns it; observability integration fetches the trace. Add a separate correlator only for future complex cross-trace merging.
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
├── hybrid.py
├── rule/
└── judge/
```

Confirmed responsibilities:

### `evaluator_protocol.py`

- Renamed from `base.py`.
- Defines the unified Evaluator contract.
- All evaluator implementations consume a common evaluation input and return a common result containing Score, Verdict, Reason, and Evidence references.

### `executor.py`

- Renamed from `engine.py` to avoid confusion with `run/engine.py`.
- Receives a completed CaseRun plus normalized Trace/Artifact references and executes all Evaluators already selected by the RunManifest/application composition.
- Builds evaluator inputs, invokes evaluators, captures evaluator execution errors/timeouts and execution metadata, and returns independent EvaluationResults.
- Does not run the target Agent, choose evaluator policy, implement evaluator rules, aggregate Run scores, make a release-gate decision, or persist data directly.

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

- `metrics.py`: calculate and aggregate Result summaries by metric, quality dimension,
  evaluator kind, and overall score. It preserves the implemented P1 behavior from
  `calc_metrics.py`, which is renamed because module names should describe the owned
  concept rather than one function.
- `gate.py`: apply the snapshotted Gate specification to evaluation Results and produce a
  Gate decision. It does not execute Evaluators or own release scheduling.
- `report.py`: assemble one structured Run report from the Run, Results, Metrics, Gate
  decision, and Trace/Artifact references. The implemented P1 behavior in `service.py`
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
- Gate answers whether one Run met configured thresholds.
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
└── lineage_queries.py
```

### `application/dataset_management.py`

- Coordinates user-facing Dataset and Case lifecycle operations: Dataset create,
  update, archive, copy, version listing, draft create/publish/discard,
  import/export, and Case add/update/delete/copy/reorder.
- Delegates invariants to `domain/`, import/export mechanics to `case/loader.py`
  and `case/export.py`, revisions and hashes to `case/versioning.py`, format
  conversion to `case/formats/`, and persistence to the storage interface.
- Existing `case.DatasetService` orchestration moves here; reusable Dataset
  mechanics remain in `case/`.
- Does not generate synthetic Cases, execute Datasets, implement formats, define
  domain models, calculate hashes, write SQL, or expose HTTP.
- Automatic generation is a separate future application use case in
  `application/dataset_generation.py`. It coordinates Target metadata,
  `case/generation/`, a model provider, and creation of a Dataset draft, then
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
  manifest construction to `run/manifest.py`, persists the Run, and selects
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
- Likely persisted areas include Datasets and versions, Runs, CaseRuns/Attempts,
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

## Next review item

```text
server/
```
