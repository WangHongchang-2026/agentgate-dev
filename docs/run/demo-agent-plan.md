# Instrumented Demo Agent Plan

## Goal

Provide a deterministic loan-domain Agent that is invoked through HTTP, records its real
behavior with the OpenTelemetry SDK, exports standard OTLP/HTTP protobuf to AgentGate, and
produces different Gate decisions for risky and fixed versions.

```text
AgentGate
  |
  | POST /invoke
  | TargetRef + Run/Case/Turn/invocation + traceparent
  v
Demo Loan Agent
  |
  +--> route Skill
  +--> call tools
  +--> update business state
  +--> produce final output
  |
  | OpenTelemetry SDK spans
  v
OTLP/HTTP protobuf exporter
  |
  | POST AgentGate /v1/traces
  v
AgentGate Trace ingestion
  |
  v
canonical Trace -> Evaluators -> Result -> Gate
```

The Demo Agent proves AgentGate's production-shaped contracts. It is not a model for
managing externally owned Agent or Skill assets.

## Current State and Gap

Implemented:

- deterministic loan-domain logic;
- four routable capabilities: loan approval, credit inquiry, repayment plan, complaint;
- risky and fixed target versions;
- credit inquiry, approval, human review, repayment, complaint, and state behavior;
- deterministic P1 Case and expected policy outcomes;
- manual construction of AgentGate `Trace` and `TraceSpan` objects;
- direct in-process execution returning a canonical Trace;
- risky version fails and fixed version passes the release Gate.

Current gaps:

- the Demo Agent is not an independently invocable HTTP service;
- it does not use the OpenTelemetry API or SDK;
- spans are manually constructed in AgentGate's canonical model;
- it does not export OTLP;
- it does not extract or propagate W3C Trace Context;
- Run, Case, Turn, and invocation attributes are not attached through a reusable
  instrumentation helper;
- AgentGate does not wait for separately arriving Demo telemetry;
- the common HTTP target adapter is not exercised by the Demo;
- the current direct Trace path can hide production integration defects.

## Scope

This increment implements:

1. a deterministic Demo Agent HTTP service;
2. normalized invoke request and response contracts;
3. OpenTelemetry SDK initialization;
4. routing, Agent, tool, state, and terminal spans;
5. W3C context extraction and propagation;
6. AgentGate correlation attributes;
7. OTLP/HTTP protobuf export to AgentGate;
8. deterministic flush/completeness behavior for the POC;
9. risky and fixed version behavior;
10. unit and full end-to-end acceptance tests.

## Non-Goals

- using a live LLM for Demo routing or decisions;
- production authentication;
- a production credential vault;
- external Agent/Skill asset CRUD;
- simulating every possible enterprise Agent framework;
- public benchmark integration;
- queue/reservation behavior;
- production distributed state storage;
- automatic optimization;
- making the Demo Agent part of AgentGate's core domain API.

The Demo remains deterministic so evaluation regressions are attributable to code and
contracts rather than model variance.

## Terms

### Demo Agent

The local deterministic loan Agent used to demonstrate target invocation, telemetry,
evaluation, and Gate behavior.

### Demo Target Version

One immutable behavior variant:

```text
loan-agent-v1-risky
loan-agent-v2-fixed
```

### Instrumentation

Code that creates OTel spans around Agent behavior. It observes the business operation
without moving policy logic into telemetry code.

### Root Span

The span covering one Case-turn Agent invocation.

### Semantic Child Span

A routing, tool, state, or terminal operation recorded with AgentGate semantic
attributes.

### OTLP Export

Transmission of ended OTel spans from the Demo process to AgentGate's standard
`POST /v1/traces` receiver.

### Inline Trace Mode

A compatibility mode where local tests return a canonical Trace directly. It is allowed
only for focused unit tests and is not the end-to-end Demo acceptance path.

## Ownership Boundaries

```text
demo/loan.py
  deterministic loan business behavior

demo/telemetry.py
  OTel provider/exporter setup and semantic span helpers

demo/server.py
  HTTP invoke transport and context extraction

run/targets/http.py
  AgentGate client-side invocation adapter

trace/
  OTLP decoding, normalization, merge, completeness, persistence

evaluator/
  judgment of the resulting canonical Trace
```

Business logic must not import AgentGate evaluator or Result code. Telemetry helpers must
not decide loan policy.

## Demo Business Behavior

### Skills

```text
loan_approval
credit_inquiry
repayment_plan
complaint
```

### Relevant Tools

```text
credit_inquiry
approve_loan
request_human_review
repayment_plan
complaint
```

### Version Difference

```text
High-risk loan application

v1-risky
  credit_inquiry
  -> approve_loan
  -> status=approved
  -> Gate FAIL

v2-fixed
  credit_inquiry
  -> request_human_review
  -> status=pending_review
  -> Gate PASS
```

No random behavior, wall-clock business decision, or external model call may change this
acceptance result.

## Service Architecture

Run the Demo Agent as a separate process:

```text
AgentGate API       http://127.0.0.1:8000
Demo Agent API      http://127.0.0.1:8010

AgentGate -> Demo Agent /invoke
Demo Agent -> AgentGate /v1/traces
```

Ports are configurable. Tests use isolated dynamic or dedicated ports.

The service exposes:

```text
GET  /health
GET  /targets
GET  /targets/{target_id}/versions
POST /invoke
```

The target catalog endpoints exist only to exercise TargetCatalogAdapter. They are not a
general asset-management API.

## Invoke Contract

Request:

```json
{
  "invocation_id": "inv-123",
  "idempotency_key": "run-1:case-1:turn-1",
  "run_id": "run-1",
  "case_id": "case-1",
  "turn_id": "turn-1",
  "target": {
    "type": "agent",
    "id": "loan-agent",
    "version_id": "loan-agent-v2-fixed"
  },
  "input": {
    "skill": "loan_approval",
    "application_id": "A-100",
    "risk": "high",
    "amount": 80000
  },
  "state": {}
}
```

Headers:

```text
Content-Type: application/json
traceparent
baggage
X-AgentGate-Run-Id
X-AgentGate-Case-Id
X-AgentGate-Turn-Id
Idempotency-Key
```

Response:

```json
{
  "invocation_id": "inv-123",
  "external_execution_id": "demo-inv-123",
  "trace_id": "0123456789abcdef0123456789abcdef",
  "output": {
    "message": "处理完成",
    "status": "pending_review"
  },
  "final_state": {
    "application_id": "A-100",
    "status": "pending_review",
    "approved": false,
    "human_review": true
  }
}
```

The response does not include manually assembled spans. Spans arrive through OTLP.

## OpenTelemetry SDK Configuration

Dependencies:

```text
opentelemetry-api
opentelemetry-sdk
opentelemetry-exporter-otlp-proto-http
```

Recommended Demo configuration:

```text
OTEL_SERVICE_NAME=agentgate-demo-loan
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:8000/v1/traces
OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf
```

The exporter endpoint is configurable and never hard-coded into loan business logic.

Use one process-wide `TracerProvider`. Do not replace the global provider per request.
The Demo may use `SimpleSpanProcessor` for deterministic POC behavior. A
`BatchSpanProcessor` mode remains available for production-shaped tests and must rely on
AgentGate Trace completeness rather than arbitrary sleeps.

The HTTP response is returned only after the root span has ended. In deterministic Demo
mode, call provider `force_flush()` with a bounded timeout before returning so the
terminal span is available promptly. Flush failure is reported as telemetry failure; it
does not change the loan decision.

## Context and Correlation

The service extracts W3C `traceparent` and `baggage` from incoming headers and starts the
root span with the extracted remote parent.

Every semantic span must carry:

```text
agentgate.run.id
agentgate.case.id
agentgate.turn.id           when present
agentgate.invocation.id
agentgate.invocation.attempt
agentgate.target.type
agentgate.target.id
agentgate.target.version
agentgate.span.kind
```

OTel child spans do not automatically inherit parent attributes. Implement a reusable
span helper or SpanProcessor enrichment mechanism that copies the request-scoped
correlation values to every exported semantic span.

Use request-local context storage. Concurrent invocations must not leak correlation
attributes into each other.

## Span Model

Example fixed-version Trace:

```text
agent.execute                         kind=agent
├── skill.route                       kind=routing
├── tool.credit_inquiry               kind=tool
├── tool.request_human_review         kind=tool
├── state.business                    kind=state
└── agent.complete                    kind=event
```

### Root Agent Span

```text
name: agent.execute
agentgate.span.kind: agent
agent.version
input field names or sanitized summary
execution status
```

Do not record unrestricted raw input by default.

### Routing Span

```text
name: skill.route
agentgate.span.kind: routing
intent
selected_skill
fallback
```

### Tool Span

```text
name: tool.<tool_name>
agentgate.span.kind: tool
tool.name
tool.arguments JSON, sanitized and bounded
tool.status
```

Tool errors record OTel exception/status and are re-raised or converted according to
business behavior. Instrumentation must not swallow them.

### State Span

```text
name: state.business
agentgate.span.kind: state
agentgate.state.json
```

State JSON uses canonical serialization and configured redaction.

### Terminal Span

```text
name: agent.complete
agentgate.span.kind: event
agentgate.trace.complete: true
agentgate.turn.complete: true
agentgate.final_output.json
agentgate.final_state.json
```

Only explicit terminal semantic attributes are interpreted as final output/state by the
Trace normalizer.

## Instrumentation Pattern

Conceptual implementation:

```python
with telemetry.agent_span(context) as root:
    with telemetry.routing_span(context) as span:
        selected_skill = route(request)
        span.set_attribute("selected_skill", selected_skill)

    with telemetry.tool_span(context, "credit_inquiry", arguments):
        credit = credit_inquiry(arguments)

    with telemetry.tool_span(context, selected_action, arguments):
        state = execute_action(selected_action, arguments)

    with telemetry.state_span(context, state):
        pass

    with telemetry.completion_span(context, output, state):
        pass
```

Span creation belongs around actual operations. Do not create all spans afterward from a
manually assembled history list.

## AgentGate Waiting Behavior

```text
HTTP target response received
        |
        v
record external execution ID and source Trace ID
        |
        v
wait for canonical Trace(run_id, case_id)
        |
        +--> complete terminal signal -> evaluate
        |
        +--> deadline -> incomplete Trace policy
```

AgentGate must not evaluate immediately just because the HTTP response arrived. It waits
for the Trace completeness policy defined in `docs/trace/ingestion-plan.md`.

No arbitrary fixed sleep is an acceptance mechanism.

## Error Semantics

| Failure | Owner | Effect |
| --- | --- | --- |
| invalid target version | Demo service/target adapter | Run configuration/execution error |
| malformed invoke request | Demo HTTP service | protocol error |
| loan business/tool failure | Demo Agent | recorded tool/Agent error span |
| OTLP export failure | telemetry layer | telemetry/Trace incomplete |
| AgentGate receiver rejection | telemetry integration | Trace incomplete/conflicted |
| evaluator crash | evaluator | evaluator ERROR |
| valid policy violation | evaluator | Agent FAIL |

Telemetry export failure must not silently produce an empty successful Trace. Business
output may still be returned, but the Run records that required evidence is incomplete.

## Idempotency and State

- the same Idempotency-Key and request content returns the same logical execution result;
- the same key with different content is rejected;
- tool/state side effects are stored in the existing Demo business-state repository;
- retries must not duplicate irreversible Demo side effects;
- invocation ID is included in all spans;
- repeated OTLP delivery is handled idempotently by Trace ingestion;
- Demo state is test-isolated by database/namespace.

## Security and Data Limits

- bind Demo service to localhost by default;
- do not treat Demo endpoints as production-authenticated APIs;
- cap request, input, output, state, and attribute sizes;
- do not record credentials or unrestricted personal data in spans;
- sanitize tool arguments before span attributes;
- record structured summaries instead of full prompts where possible;
- OTLP endpoint configuration comes from environment or typed config;
- bound force-flush timeout;
- never let input choose an arbitrary exporter URL;
- never expose protected stack traces in HTTP responses.

## Rules to Avoid Design Drift

1. The end-to-end Demo must use real OTel SDK spans and OTLP export.
2. Do not manually build canonical Trace as the main Demo path.
3. Keep inline Trace only for focused unit tests.
4. Do not move loan policy into telemetry helpers.
5. Do not use a live LLM in deterministic acceptance tests.
6. Do not use terminal text parsing as telemetry.
7. Do not assume root-span attributes automatically appear on child spans.
8. Do not send plaintext secrets or unrestricted input/state in span attributes.
9. Do not use fixed sleeps to wait for exported spans.
10. Do not return before the root/terminal span has ended in deterministic mode.
11. Do not interpret generic span names as AgentGate semantics.
12. Do not make the Demo service own Dataset, Evaluator, or Result objects.
13. Do not make AgentGate accept missing Run/Case correlation.
14. Do not change risky/fixed policy outcomes while refactoring instrumentation.
15. Keep the Demo service replaceable by a real external Agent platform.

## Parallel Development Boundary

```text
Demo Agent owner
  demo/loan.py
  demo/telemetry.py
  demo/server.py
  Demo-focused tests

Target integration owner
  domain/target.py
  run/targets/

Trace owner
  domain/trace.py
  trace/
  Trace persistence

Shared integration
  pyproject.toml
  control_plane/service.py
  run/core.py
  server test fixtures
```

Implement business instrumentation with the OTel in-memory exporter first. Integrate the
real HTTP/protobuf exporter only after the Trace receiver contract lands. Use separate
branches/worktrees and merge shared dependencies deliberately.

## Code Change Map

Status labels:

- `[ADD]` create;
- `[MOD]` modify;
- `[DEL]` delete;
- `[KEEP]` reuse;
- `[DEFER]` retain for later.

```text
agentgate-goal/
├── pyproject.toml                              [MOD] Add OTel API/SDK/HTTP exporter Demo deps
│
├── src/agentgate/
│   ├── demo/
│   │   ├── __init__.py                        [MOD] Export Demo service/config
│   │   ├── loan.py                            [MOD] Separate business behavior from Trace building
│   │   ├── provider.py                        [KEEP] Deterministic action provider
│   │   ├── telemetry.py                       [ADD] OTel setup, context, semantic span helpers
│   │   ├── models.py                          [ADD] Invoke request/response models
│   │   └── server.py                          [ADD] FastAPI Demo Agent service
│   │
│   ├── run/
│   │   └── targets/
│   │       ├── demo.py                        [ADD] Demo catalog configuration
│   │       └── http.py                        [MOD] Invoke Demo through common HTTP adapter
│   │
│   ├── trace/
│   │   ├── normalizer.py                      [MOD] Demo semantic output/state attributes
│   │   └── receivers/otlp_http.py             [MOD] OTLP HTTP protobuf receiver
│   │
│   ├── control_plane/service.py               [MOD] Select Demo TargetRef through catalog
│   └── server/application.py                  [MOD] Wait for correlated complete Trace
│
├── tests/
│   ├── test_demo_business.py                  [ADD] Logic without telemetry transport
│   ├── test_demo_telemetry.py                 [ADD] In-memory OTel span tree/attributes
│   ├── test_demo_server.py                    [ADD] Invoke contract and context extraction
│   ├── test_otel_demo_export.py               [ADD] Real HTTP/protobuf export to AgentGate
│   ├── test_demo_engine.py                    [MOD] HTTP+OTel risky/fixed Gate outcomes
│   ├── test_http_target.py                    [MOD] Demo service through common adapter
│   └── test_api.py                            [MOD] Launch and wait end-to-end
│
└── docs/
    ├── run/README.md                          [MOD] Link this plan
    ├── run/demo-agent-plan.md                 [ADD] This document
    ├── progress.md                            [MOD] Only after verification
    └── capability-mapping.md                  [MOD] Only after acceptance
```

No source file is deleted. Manual Trace construction is removed from the primary Demo
path only after the OTel path passes end-to-end acceptance.

## Delivery Checkpoints

### 1. Separate Business Logic

- preserve deterministic risky/fixed behavior;
- return normalized output, state, and action records without constructing Trace;
- unit test policy behavior.

### 2. In-Memory OTel Instrumentation

- add SDK configuration and semantic span helpers;
- verify root/child relationships and correlation attributes;
- verify routing, tool, state, terminal, and error spans;
- use in-memory exporter for fast deterministic tests.

### 3. Demo HTTP Service

- add health, catalog, versions, and invoke endpoints;
- extract W3C context;
- validate exact target version and idempotency;
- return output/state/execution/Trace identity.

### 4. Real OTLP Export

- configure standard Python OTLP HTTP protobuf exporter;
- send to AgentGate `/v1/traces`;
- force-flush with bounded timeout in deterministic mode;
- verify receiver normalization and completeness.

### 5. AgentGate End-to-End

- invoke Demo through common HTTP TargetExecutionAdapter;
- wait for canonical Trace without fixed sleep;
- evaluate risky and fixed versions;
- display persisted span evidence and Gate decision;
- verify restart-safe report retrieval.

## Acceptance Tests

At minimum:

1. Demo service health succeeds.
2. Catalog exposes one Agent with exact risky/fixed versions.
3. Unknown version is rejected and never falls back to latest.
4. High-risk risky version calls credit inquiry then direct approval.
5. High-risk fixed version calls credit inquiry then human review.
6. Root span extracts incoming W3C parent context.
7. Every semantic span contains Run/Case/invocation/target correlation.
8. Turn correlation is present when supplied.
9. Routing span records selected Skill.
10. Tool spans record sanitized name, arguments, status, and errors.
11. State span records canonical bounded state.
12. Terminal span records completion and explicit output/state signals.
13. Root and terminal spans end before deterministic flush.
14. Standard Python exporter sends OTLP/HTTP protobuf to AgentGate.
15. AgentGate creates one canonical Trace from exported spans.
16. AgentGate does not evaluate before Trace completeness.
17. Export failure produces incomplete telemetry, not synthetic success.
18. Duplicate span delivery does not duplicate evaluator evidence.
19. Concurrent invocations do not mix correlation attributes.
20. Reused idempotency key with different content is rejected.
21. Risky version Gate remains FAIL for the expected policy reasons.
22. Fixed version Gate remains PASS.
23. Report evidence links to stable canonical span IDs.
24. No credential or unrestricted sensitive state appears in logs/API errors.
25. Inline Trace mode is absent from the full end-to-end acceptance path.

End-to-end command-level acceptance:

```text
start AgentGate API with OTLP HTTP protobuf receiver
  -> start instrumented Demo Agent
  -> launch risky evaluation through AgentGate API
  -> Demo exports routing/tool/state/terminal spans
  -> AgentGate waits, normalizes, evaluates, returns Gate FAIL
  -> launch fixed evaluation
  -> AgentGate returns Gate PASS
  -> result drill-down displays actual OTel-derived evidence
```

## Deferred Work

- live LLM-backed Demo behavior;
- BatchSpanProcessor performance/load testing;
- production authentication and TLS;
- production credential management;
- external scheduler execution;
- multi-process/distributed Demo tools;
- public deployment of Demo Agent;
- additional business domains;
- OTel logs and metrics from Demo Agent;
- production sampling strategy.
