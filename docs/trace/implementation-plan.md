# Trace Implementation Plan

Last updated: 2026-09-06

## 1. Purpose

AgentGate evaluates observed Agent behavior. Trace data must therefore come from real
Agent execution instrumentation, not from fabricated evaluation fixtures or an adapter
guessing which internal operations occurred.

```text
Agent execution
  -> OpenTelemetry spans
  -> capture or transport integration
  -> canonical normalization
  -> completed Domain Trace
  -> RunEngine
  -> Evaluators
```

The deterministic Loan Agent is a demo Target, but the spans emitted while it executes
are real OpenTelemetry spans.

## 2. Two Capture Modes

### Local Demo

```text
DemoLoanTargetAdapter
  -> establishes W3C Trace Context
  -> LoanAgent.invoke() emits OTel spans
  -> official InMemorySpanExporter receives finished spans
  -> CaseExecutionResult returns the OTel trace_id
  -> in-memory observability adapter maps SDK span data
  -> trace/normalizer.py builds one Domain Trace
  -> RunEngine receives the resolved Domain Trace
```

The in-memory exporter replaces only network transport. It does not fabricate spans,
tool calls, outputs, or state changes.

### External Platform

```text
AgentGate Target adapter
  -> calls external Agent with correlation context
  -> external Agent emits OTel
  -> OTLP/HTTP or an existing observability platform
  -> AgentGate observability integration retrieves completed telemetry
  -> trace/normalizer.py builds one Domain Trace
  -> RunEngine resolves it by trace_id
```

An external platform may store traces in LoongSuite, Langfuse, Phoenix, or another OTel
backend. AgentGate should integrate with that system instead of becoming a complete
observability platform.

## 3. Final Ownership

```text
trace/
├── normalizer.py
└── redaction.py

integrations/observability/
├── in_memory.py
├── otlp_http_receiver.py
└── stored_trace.py             only when external retrieval is implemented

demo/
└── loan.py                     emits spans through an injected OTel tracer
```

Do not create empty integration files. `stored_trace.py` is deferred until a real
external Trace retrieval path exists.

### `trace/normalizer.py`

Owns semantic conversion from supported OTel data into `domain.Trace` and
`domain.TraceSpan`. It recognizes AgentGate correlation/completion attributes and
supported GenAI/OpenInference aliases.

It does not receive HTTP, configure an OTel SDK, query storage, poll, redact, or invoke
Evaluators.

### `trace/redaction.py`

Removes or masks credentials, personal data, financial data, sensitive Tool arguments
and results, and code secrets before Trace data is sent to a Judge, UI, Dataset
generator, report, or external output.

It does not alter stored raw evidence silently. Redaction returns a separate protected
view. Implement it when its first Judge/UI caller is reviewed.

### `integrations/observability/in_memory.py`

Configures an official OTel SDK `TracerProvider`, span processor, and
`InMemorySpanExporter` for one local execution environment. It selects finished spans
for one execution, delegates semantic conversion to the normalizer, and returns a
completed Domain Trace.

It is real local telemetry capture, not a mock exporter implemented by AgentGate.

### `integrations/observability/otlp_http_receiver.py`

Owns lightweight OTLP/HTTP transport handling: content type, body limits, JSON or
protobuf decoding when supported, protocol response, and delegation to the normalizer
and persistence boundary.

It is not an OpenTelemetry Collector, long-term telemetry store, or vendor UI.

### `integrations/observability/stored_trace.py`

Future adapter that waits for or retrieves a completed Trace from AgentGate storage or
an external observability backend. It supplies the `TraceResolver` callable used by
RunEngine. Polling, timeout, and backend-specific APIs stay here, not in Engine.

## 4. Correlation Contract

RunEngine creates one execution identity and W3C `traceparent`. The Target adapter
activates that context before invoking the Agent. The adapter-owned root/completion
span carries:

```text
agentgate.run.id
agentgate.case.id
agentgate.execution.id
agentgate.operation.type
```

Each adapter-owned Turn span carries `agentgate.turn.id`. Child Agent spans inherit OTel
Trace Context, not root-span attributes, and do not need AgentGate Run, Case, or
execution IDs.

Compatibility aliases currently accepted by the P1 receiver may be read during
migration, but new code emits only the dotted names. No compatibility models or duplicate
fields are introduced.

Correlation rules:

- Trace and Span IDs are lowercase OTel identifiers;
- a Trace cannot move to a different Run or Case;
- every normalized Span uses the owning source Trace ID;
- Run, Case, and execution ownership must appear on at least one span and normally lives
  on the adapter-owned root/completion span;
- any child span that explicitly declares ownership must match the Trace owner;
- each Turn outcome is linked by `agentgate.turn.id`;
- missing Run/Case correlation is rejected, never assigned to a shared fallback owner;
- credential values never appear in correlation attributes.

## 5. Completion Contract

Evaluators must not receive a partial Trace. The terminating Case span records:

```text
agentgate.trace.complete = true
agentgate.final.output = <structured JSON value>
agentgate.final.state = <structured JSON object>
```

Each completed Turn span records:

```text
agentgate.turn.id
agentgate.turn.complete = true
agentgate.turn.output = <structured JSON value>
agentgate.turn.state = <structured JSON object>
```

Local capture resolves only after the Agent invocation has ended and the SDK has
flushed all spans. External capture resolves only after an explicit completion signal
and required final output/state are present. Timeout produces a Target execution error;
it does not convert a partial trace into a completed Domain Trace.

## 6. Instrumentation Rules

The demo Agent emits spans around operations that actually execute:

```text
Case execution span
  ├── Turn span
  │   ├── routing span
  │   ├── model/decision span
  │   ├── tool spans
  │   └── state-change span
  └── Turn span ...
```

- Span names describe operations, not evaluator conclusions.
- `agentgate.operation.type` remains extensible and uses stable English values.
- Tool spans record safe arguments/results required for evaluation.
- Exceptions set OTel error status and sanitized exception information.
- The Agent does not import AgentGate Domain Trace classes.
- The Agent does not accept Run, Case, or evaluator objects.
- The adapter owns Run/Case/Turn correlation; the Agent owns its internal operation spans.
- Final output and state are recorded once at their completion boundary.

## 7. Data And Security Rules

- OTel attributes must use OTel-supported primitive values; structured values use
  canonical JSON encoding at the instrumentation boundary.
- Credentials, authorization headers, provider keys, and credential references are not
  span attributes.
- Attribute count, string length, body size, span count, and nesting depth are bounded.
- Duplicate delivery with identical content is idempotent.
- Conflicting content for the same immutable Span identity is rejected, not overwritten.
- The local in-memory exporter is scoped and cleared between Case executions so spans
  cannot leak across Runs.
- Raw telemetry and redacted presentation data remain distinguishable.

## 8. Current Gaps

- `LoanAgent.execute()` manually constructs AgentGate Trace objects.
- The official OpenTelemetry SDK is not installed.
- The current normalizer accepts missing correlation through fallback Run/Case values.
- The current receiver writes each normalized batch directly and can replace an earlier
  partial snapshot.
- Completion, final output, final state, and Turn outcomes are not derived from OTLP.
- The receiver still lives under `trace/receivers/` instead of integrations.
- Empty Trace importer, external, graph, evidence, and model scaffolds remain.
- RunEngine has an injected resolver but only test resolvers currently exist.

## 9. Source Assessment

### `goal/p1-demo`

Preserve:

- OTLP JSON AnyValue decoding;
- resource and span attribute merging;
- timestamp and status conversion;
- lightweight receiver-to-repository flow;
- current Domain Trace/TraceSpan contracts and evaluator evidence behavior.

Refactor or reject:

- reject fallback ownership such as `otlp-external` and `external-trace`;
- reject direct Trace construction in `LoanAgent`;
- move HTTP transport from `trace/receivers/` to integrations;
- remove empty Trace scaffolds rather than copying them.

### `integration/p1-new`

Preserve as design references:

- strict correlation and canonical dotted attributes;
- bounded ingestion;
- completion markers;
- deterministic ordering, deduplication, conflict detection, and partial-success ideas;
- pending execution correlation by trace ID.

Do not copy directly:

- obsolete Trace domain models and status fields;
- repository APIs not present in the current refactor;
- compatibility-heavy aliases beyond the narrow P1 migration need;
- a full ingestion service before the demo or external path exercises it.

### Official OpenTelemetry Libraries

Use the official OTel API/SDK and in-memory exporter. Do not implement custom tracing,
Trace ID generation, context propagation, span processors, or an exporter protocol.
Exact package constraints must be verified against official documentation during the
first implementation checkpoint.

### From Scratch

- AgentGate semantic attribute mapping and completion rules;
- conversion from captured SDK spans through the canonical normalizer;
- the RunEngine resolver composition;
- focused tests proving that spans correspond to operations that really executed.

Reuse means preserving validated behavior under current contracts, not copying an old
module wholesale.

## 10. Implementation Sequence

Each file requires a source assessment and explicit approval before implementation.

1. Confirm this Trace plan and record the existing OTLP behavior baseline.
2. [complete] Review `trace/normalizer.py` input contract, correlation, completion,
   and output.
3. Add verified official OTel SDK dependencies.
4. Review and implement `integrations/observability/in_memory.py`.
5. Review and instrument the clean `LoanAgent.invoke()` contract.
6. Review and implement `integrations/targets/demo_loan.py`.
7. Connect in-memory resolution to RunEngine and migrate the demo execution path.
8. Review and move the lightweight receiver to
   `integrations/observability/otlp_http_receiver.py`.
9. Add `stored_trace.py` only with a real external retrieval caller.
10. Review and implement `trace/redaction.py` with its first Judge/UI caller.
11. Remove old receiver and empty Trace scaffolds after all imports migrate.
12. Run focused tests, the complete backend suite, and an end-to-end demo Run.

## 11. Test Plan

### Real Local Capture

- executing a routing branch emits a routing span;
- a Tool span exists only when that Tool executes;
- risky and fixed Agent versions produce different real Tool/state spans;
- multi-turn execution preserves Turn ordering and conversation state;
- two Case executions cannot share captured spans;
- Trace IDs come from OTel context and match CaseExecutionResult.

### Normalization

- canonical and supported alias attributes normalize consistently;
- missing Run/Case correlation fails;
- OTel timestamps, status, parent IDs, events, and safe attributes are preserved;
- final output/state and Turn outcomes are derived only from completion signals;
- malformed structured attributes fail with stable locations;
- duplicate Spans are idempotent and conflicts fail closed when multi-batch ingestion is
  implemented.

### External Receiver

- valid OTLP JSON is accepted and persisted;
- unsupported content type, malformed payload, and limit violations fail safely;
- partial telemetry is not exposed to Evaluators as complete;
- credentials and oversized payloads do not enter logs or persisted errors.

### Regression

- existing risky/fixed scores and release-gate outcomes remain equivalent;
- current evaluator Span evidence remains valid;
- full backend tests pass;
- one real demo Run produces a completed Trace and Results without manually constructing
  TraceSpan objects in the Agent.

## 12. Dependency Rules

```text
demo Agent -> OpenTelemetry API

integrations/observability -> OpenTelemetry SDK/exporters
integrations/observability -> trace/normalizer.py
integrations/observability -> storage repository interface

trace/normalizer.py -> domain Trace models
RunEngine -> injected TraceResolver callable
```

`domain/` and `trace/` do not depend on FastAPI, Celery, SQLite implementations, or OTel
SDK exporters. `LoanAgent` does not depend on AgentGate evaluation models.

## 13. Completion Gate

Trace refactoring is complete when:

- the Demo Agent emits real OTel spans and no longer constructs Domain Trace objects;
- local in-memory capture produces a complete Domain Trace;
- RunEngine evaluates only explicitly completed Traces;
- correlation and completion attributes are stable and documented;
- HTTP transport lives under integrations and does not own semantic normalization;
- partial, duplicate, conflicting, and sensitive telemetry follow explicit rules;
- obsolete empty Trace scaffolds are removed;
- the risky/fixed demo behavior and evaluator evidence remain correct;
- focused tests, the complete backend suite, and an end-to-end demo Run pass.

## 14. Implementation Decisions

### `trace/normalizer.py`

Status: implemented; 229 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Reuse AnyValue, attribute, timestamp, status, and event parsing after strengthening validation. |
| `goal/p1-demo` | Reject fallback Run/Case ownership, random missing IDs, payload-order sequencing, and incomplete Trace output. |
| `integration/p1-new` | Adapt strict correlation, canonical aliases, completion markers, and deterministic ordering. |
| `integration/p1-new` | Reject obsolete TraceBatch/status models and the unexercised ingestion service. |
| Current refactor | Reuse immutable `Trace` and `TraceSpan` Domain contracts. |
| From scratch | Add shared `normalize_span()` and `assemble_trace()` functions used by OTLP and in-memory integrations. |

### `integrations/observability/in_memory.py`

Status: implemented; verified with OTel 1.44.0; 233 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Reject; it contains no OTel SDK capture implementation. |
| `integration/p1-new` | Use lifecycle and correlation ideas only; reject obsolete Trace ingestion models and services. |
| Current refactor | Reuse `normalize_span()`, `assemble_trace()`, and the RunEngine `TraceResolver` callable shape. |
| Official OTel | Use a private `TracerProvider`, `SimpleSpanProcessor`, and `InMemorySpanExporter`. |
| From scratch | Implement execution filtering, SDK-to-normalizer mapping, bounded capture, and Case isolation. |

### Demo Agent And Target Adapter

Status: implemented; focused Trace and adapter tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve deterministic loan behavior and risky/fixed versions; reject the Case-aware `execute()` API and manual Domain Trace construction. |
| `integration/p1-new` | Preserve W3C propagation as a design reference; reject manual OTLP fabrication and obsolete adapter models. |
| Current refactor | Reuse `TargetAdapterProtocol`, `InMemoryTraceCapture`, and canonical Trace completion rules. |
| From scratch | Implement `LoanAgent.invoke()`, real OTel business spans, Case/Turn adapter spans, and parent-based Turn selection. |
