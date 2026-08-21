# AgentGate Architecture

## Positioning

AgentGate is an OpenTelemetry-native, framework-independent evaluation harness for enterprise agent quality gates.

It is not only a trace viewer or generic LLM eval library. Its core job is to answer:

```text
Can this agent version be released safely?
```

## Core Flow

```text
Case
  -> Target Agent
  -> Run + Trace
  -> Evaluators
  -> CheckResults + Results
  -> Metric Summaries
  -> Report + Gate Decision
```

## Five Core Modules

### Case

Defines what should be tested.

Includes:

- input messages
- initial state
- typed Expectations and Conditions
- required actions
- forbidden actions
- tool argument expectations
- workflow constraints
- final state expectations
- policy references
- provenance and review status

### Run

Represents one execution of a case or batch.

Includes:

- run config
- target agent config
- evaluator config snapshot
- metric aggregation plan snapshot
- release gate configuration snapshot
- canonical snapshot content hash
- lifecycle status
- timeout, retry, concurrency
- run events

### Trace

Represents what happened during execution.

Includes:

- raw spans
- normalized agent execution graph
- LLM calls
- tool calls
- retrieval events
- approvals
- retries
- errors
- state-changing actions
- final business state
- final target output

OpenTelemetry and future provider formats enter through adapters under
`trace/receivers/` or `trace/importers/`. Evaluators consume only the canonical
vendor-neutral Trace in `domain/trace.py`.

### Evaluator

Defines how behavior is judged.

Evaluator product categories are:

- Rule
- LLM-as-a-Judge
- Hybrid

P1 implements deterministic Rule evaluators for:

- skill routing
- required tool called
- forbidden tool not called
- tool argument expectations
- policy rule match
- final state expectations

Operators are reusable comparisons used inside Rule evaluators. They are not Metrics.

### Result

Stores Outcome, nullable score, explanation, detailed checks, and evidence.

Each result should link back to:

- evaluator name and version
- score
- pass/fail/review/not-applicable/error Outcome
- reason
- evidence span IDs
- policy/document references

An evaluator ERROR is different from an agent FAIL. ERROR fails the release gate closed
but does not assign an agent failure stage. `primary_failure_step` is the first
trace-sequenced stage where an agent failure was observed; it is not a proven root cause.

## Code Layers

```text
domain/       Immutable Pydantic data models shared across boundaries
evaluator/    Plan validation, observations, operators, Rules, scoring, runner
result/       Multi-Result metric calculation, release Gate, report construction
run/          Target execution and complete Run orchestration
trace/        Telemetry receivers/importers and canonical normalization
control_plane/ Local control-plane service used by CLI and FastAPI
```

Dependencies point toward `domain/`; domain models never import runtime services.

## Product Modules

The core evaluation flow is intentionally small. Higher-level product capabilities compose
around it:

```text
Case -> Run + Trace -> Evaluator -> Result -> Metric / Gate
          ^                            |
          |                            v
        Queue                     Experiment
                                       |
                                       v
                              Optimizer + Lineage
```

### Experiment

Owns experiment definitions, controlled variant assignment, paired statistical analysis,
comparison reports, and winner or release decisions. It uses `result/compare.py` as a
low-level comparison utility.

### Queue

Owns public reservation and queue APIs, queue state, resource-key allocation, cancellation,
and start-time estimates. `run/scheduler.py` remains an internal execution abstraction. The
POC may use a local worker, while production can integrate an external scheduler through an
adapter rather than replacing it.

### Optimizer

Consumes failed results and trace evidence to cluster badcases, form root-cause hypotheses,
and produce prioritized recommendations. Initial versions require human review and never
modify target agents automatically.

### Lineage

Tracks immutable relationships among datasets, cases, evaluators, prompts, models, agents,
skills, runs, experiments, and results. `case/versioning.py` owns case revisions and registers
those revisions in the broader lineage graph.

## Entry Points

```text
CLI      -> control services -> core modules
REST API -> control services -> core modules
Web UI   -> REST API -> control services -> core modules
Java SDK -> REST API / OTLP -> control services -> core modules
```

CLI and Web should expose the same major operations, but Web calls the REST API while CLI can call the control layer directly.

## Technology Choices

Initial backend:

- Python 3.11+
- Pydantic v2
- Typer CLI
- FastAPI REST API
- SQLite first
- PostgreSQL later
- OpenTelemetry/OTLP for trace interoperability

Initial Web:

- Vue 3
- TypeScript
- Vite

## Repository Strategy

Start as one repository:

```text
agentgate/
  src/agentgate/
  web/
  docs/
  examples/
  tests/
```

Split only when needed:

- Web UI has an independent release cycle.
- Enterprise control plane becomes large.
- Go service is needed for a high-performance gateway or scheduler.
- Multiple teams own backend and frontend separately.
