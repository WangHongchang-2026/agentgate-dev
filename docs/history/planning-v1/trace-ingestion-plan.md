# Canonical Trace Ingestion Plan

> [!IMPORTANT]
> Pre-refactor design record. Behavior and acceptance criteria remain useful, but file
> paths and module ownership are superseded by
> [the architecture review ledger](../architecture-review-ledger.md).


## Goal

Build a deterministic, idempotent telemetry path that can receive one or many OTLP
batches and produce exactly one canonical evaluation Trace for each Run Case.

```text
Target execution
      |
      +--> inline Trace
      |
      +--> one or more OTLP batches
                    |
                    v
             receiver + decoder
                    |
                    v
            correlation validation
                    |
                    v
          normalized span persistence
                    |
                    v
          merge + dedupe + ordering
                    |
                    v
       canonical Trace completeness check
                    |
             +------+------+
             |             |
          complete      incomplete
             |             |
             v             v
        Evaluators     wait/timeout policy
```

This plan consumes the Run/Case/Turn/invocation correlation contract defined by
`docs/run/external-target-plan.md`. It does not redefine target invocation.

## Current State and Gap

Implemented:

- immutable canonical `Trace`, `TraceSpan`, and `TraceTurn` models;
- routing, agent, tool, state, and generic event span kinds;
- OTLP/HTTP JSON endpoint and receiver boundary;
- basic OTLP AnyValue conversion;
- normalization of OTLP resource/span attributes;
- persistence and retrieval by Run and Case;
- evaluator evidence referring to canonical span IDs;
- basic receiver integration test.

Current gaps and risks:

- absent correlation becomes `run_id="otlp-external"` and
  `case_id="external-trace"` instead of being rejected or quarantined;
- current attribute names use `agentgate.run_id` and `agentgate.case_id` while the target
  plan defines canonical dotted names;
- one OTLP request creates independent Trace objects grouped by source Trace ID;
- SQLite enforces one row per Run/Case and `INSERT OR REPLACE` overwrites the prior batch;
- duplicate OTLP delivery is not explicitly idempotent;
- span conflicts are not detected;
- span sequence is assigned from list position inside one received batch;
- timestamps from OTLP are not parsed;
- ordering changes when batches arrive in a different order;
- canonical Trace identity is generated randomly;
- final output, final state, turns, invocation attempts, and completeness are not derived;
- late-arriving telemetry can replace data after evaluation;
- there is no partial-success ingestion report;
- OTLP importers and OTLP/gRPC are empty boundaries;
- evaluators can receive an empty or incomplete Trace without an explicit policy.

## Scope

This increment defines and implements:

1. canonical correlation attribute names and legacy aliases;
2. strict correlation validation;
3. normalized TraceBatch and span ingestion;
4. idempotent span persistence;
5. deterministic canonical Trace identity;
6. multi-batch merge and span deduplication;
7. deterministic global span ordering;
8. Trace completeness and conflict states;
9. inline and OTLP telemetry convergence;
10. late-arrival behavior;
11. bounded OTLP/HTTP protobuf and JSON ingestion;
12. repository/API changes and focused tests.

## Non-Goals

- target discovery or invocation;
- evaluator algorithms;
- production OTLP/gRPC implementation;
- Jaeger or vendor-specific importer implementation;
- arbitrary raw telemetry data lake;
- distributed stream processing;
- long-term retention policy;
- cross-tenant authorization;
- full OpenTelemetry Collector replacement;
- automatic root-cause analysis;
- UI Trace graph redesign.

The design keeps extension boundaries for those capabilities.

## Terms

### Source Trace ID

The W3C/OpenTelemetry `trace_id` emitted by an instrumented target. One evaluation Case
may have multiple source Trace IDs because it has multiple turns, retries, sub-agents, or
separate executions.

### Source Span ID

The OpenTelemetry `span_id` within one source Trace ID.

### Span Identity

Within one canonical evaluation Trace:

```text
(run_id, case_id, source_trace_id, source_span_id)
```

The same identity delivered again with identical canonical content is a duplicate. The
same identity delivered with different immutable content is a conflict.

Run and Case are part of the identity because trace-only replay may intentionally evaluate
the same imported source Trace in more than one AgentGate Run.

### Trace Batch

One decoded telemetry delivery. A batch may contain spans for multiple source traces,
Runs, Cases, turns, or invocations.

### Canonical Trace

AgentGate's evaluation view aggregating all accepted spans, turns, output, and state for
one logical Run Case:

```text
(run_id, case_id) -> one canonical Trace
```

Canonical Trace is not the same as one OpenTelemetry source trace.

### Canonical Trace ID

A deterministic AgentGate identity derived from Run ID and Case ID. It does not replace
source Trace IDs stored on spans.

### Invocation

One target-execution attempt identified by `invocation_id`. Multiple invocations may
belong to one Case because of turns or retries.

### Turn

One ordered conversational interaction within a multi-turn Case. A turn may have one or
more target invocations.

### Duplicate

A previously accepted source span delivered again with the same canonical content.
Duplicates are ignored idempotently and counted in the ingestion report.

### Conflict

The same source span identity delivered with different immutable data. Conflicts are
recorded and must not be resolved by last-write-wins.

### Orphan Telemetry

Telemetry that cannot be correlated to a valid Run and Case. It is rejected or placed in
a bounded quarantine, never attached to a shared fallback Run/Case.

### Completeness

Whether enough execution and telemetry evidence has arrived to create the stable
canonical Trace permitted by the Run's Trace policy.

### Late Arrival

A valid new span or output signal arriving after a canonical Trace was marked complete or
after evaluator Results were produced.

## Ownership Boundaries

```text
run/targets/
  creates and propagates correlation context

trace/receivers/
  handles transport, payload limits, decoding, and protocol response

trace/normalizer.py
  converts supported source data into normalized spans/signals

trace/service.py
  validates correlation, merges, deduplicates, detects conflicts,
  computes ordering, and determines completeness

domain/trace.py
  owns persisted canonical Trace meaning

storage/
  persists batches/spans/state atomically and idempotently

run/
  waits for Trace completeness and decides timeout behavior

evaluator/
  reads complete canonical Trace and never parses OTLP

server/
  delegates OTLP requests to receiver/service
```

## Correlation Contract

### Canonical Attributes

New target integrations emit:

```text
agentgate.run.id
agentgate.case.id
agentgate.turn.id            optional
agentgate.invocation.id
agentgate.invocation.attempt
agentgate.target.type
agentgate.target.id
agentgate.target.version
```

W3C propagation uses:

```text
traceparent
baggage
```

### Legacy Aliases

During one compatibility window, the normalizer may accept:

```text
agentgate.run_id  -> agentgate.run.id
agentgate.case_id -> agentgate.case.id
turn_id           -> agentgate.turn.id
```

Rules:

- canonical name wins only when the alias is absent;
- canonical and legacy values that disagree cause a correlation conflict;
- normalized spans store canonical names only;
- emitters must use canonical names immediately;
- remove alias support in a versioned later change.

### Required Correlation

At minimum every accepted evaluation span requires:

```text
run_id
case_id
source_trace_id
source_span_id
```

`invocation_id` is required for externally invoked targets after the target integration
contract is implemented. Turn ID is required for multi-turn Cases.

The ingestion service verifies that:

- the Run exists;
- the Case belongs to the snapshotted DatasetVersion;
- turn ID belongs to the Case when present;
- invocation ID belongs to the Run/Case/Turn when present;
- target identity attributes, when present, match TargetSnapshot.

No default Run or Case identity is permitted.

## Domain Model

### TraceStatus

Add to `domain/trace.py`:

```python
class TraceStatus(StrEnum):
    COLLECTING = "collecting"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    CONFLICTED = "conflicted"
```

`COLLECTING` means more telemetry may normally arrive. `INCOMPLETE` means the Trace
deadline elapsed without required signals. `CONFLICTED` means accepted identity/content
cannot be reconciled safely.

### TraceSpan

Extend the canonical model:

```python
class TraceSpan(DomainModel):
    source_trace_id: str
    source_span_id: str
    parent_span_id: str | None
    run_id: str
    case_id: str
    turn_id: str | None
    invocation_id: str | None
    invocation_attempt: int
    name: str
    kind: SpanKind
    start_time_unix_nano: int | None
    end_time_unix_nano: int | None
    sequence: int
    attributes: FrozenJsonObject
    status: str
    content_sha256: str
```

The existing random `id` is replaced by a deterministic canonical span key or becomes a
derived presentation ID. Evaluator evidence must remain stable across duplicate delivery
and canonical Trace reconstruction.

### TraceTurn

Extend:

```python
class TraceTurn(DomainModel):
    turn_id: str
    turn_index: int
    input: FrozenJsonObject
    output_present: bool
    output: FrozenJsonValue
    state_present: bool
    state: FrozenJsonObject
    invocation_ids: tuple[str, ...]
    completed: bool
```

### Trace

Extend:

```python
class Trace(DomainModel):
    id: str
    run_id: str
    case_id: str
    status: TraceStatus
    spans: tuple[TraceSpan, ...]
    turns: tuple[TraceTurn, ...]
    final_output_present: bool
    final_output: FrozenJsonValue
    final_state_present: bool
    final_state: FrozenJsonObject
    source_trace_ids: tuple[str, ...]
    conflict_count: int
    completed_at: datetime | None
    content_sha256: str
```

Canonical Trace ID is deterministic from the canonical serialization of:

```text
namespace = "agentgate-trace-v1"
run_id
case_id
```

Trace content hash includes status, ordered spans, turns, final output/state, and conflict
metadata. It excludes the hash field itself.

Presence flags distinguish an absent output/state signal from a present JSON null or an
intentionally empty object. Normalizers and evaluators must not infer presence from the
value alone.

### Runtime Ingestion Models

Add under `trace/models.py`:

```text
TraceBatch
NormalizedSpan
NormalizedSignal
IngestionReport
TraceConflict
TraceCompletenessPolicy
```

These models distinguish transport/batch state from the canonical evaluation Trace.

## OTLP Normalization

### Supported Input

Initial support:

- OTLP/HTTP protobuf traces as the primary standard SDK path;
- OTLP/HTTP JSON traces for tests, debugging, and compatible exporters;
- `resourceSpans`;
- `scopeSpans` and legacy `instrumentationLibrarySpans`;
- standard AnyValue string, boolean, integer, double, bytes, array, and key-value list;
- span start/end Unix nanoseconds;
- status code/message;
- resource, scope, and span attributes;
- events and links retained as bounded normalized attributes or child event records.

OTLP/gRPC remains deferred. HTTP/protobuf is required so the instrumented Demo Agent can
use the standard OpenTelemetry Python OTLP exporter without a custom exporter.

### Validation

Transport validation checks:

- supported Content-Type;
- configured request-byte limit;
- JSON object root;
- `resourceSpans` array;
- bounded resources, scopes, spans, attributes, events, links, key length, and value size;
- valid hex lengths for source Trace and Span IDs;
- non-negative timestamps and end not before start;
- valid correlation field types.

One malformed span should not necessarily reject valid independent spans. The receiver
returns a bounded partial-success report.

### Span Kind Mapping

Prefer explicit AgentGate semantic kind:

```text
agentgate.span.kind = routing | agent | tool | state | event
```

Accept the current `agentgate.kind` as a temporary alias. Unknown or absent semantic kind
maps to `event` and preserves the source OpenTelemetry span kind in attributes.

Do not infer tool, routing, or state semantics from arbitrary span names.

### Output and State Signals

Final output/state may come from:

1. normalized TargetExecutionResult;
2. an explicit terminal AgentGate semantic span/event;
3. a trusted trace importer.

Precedence:

```text
execution result supplied by AgentGate target adapter
  > explicit terminal semantic signal
  > absent
```

Two sources at the same precedence with different canonical values create a conflict.
Lower-precedence disagreement is recorded but cannot silently overwrite the authoritative
value.

Generic attributes are never guessed to be final output or final state.

## Ingestion Pipeline

```text
HTTP request
  -> enforce transport limits
  -> decode OTLP JSON
  -> normalize each span/signal
  -> validate correlation and Run membership
  -> calculate canonical content hash
  -> transactionally insert new spans
  -> count identical duplicates
  -> record identity/content conflicts
  -> rebuild canonical Trace
  -> evaluate completeness
  -> return IngestionReport
```

### IngestionReport

```text
accepted_spans
duplicate_spans
rejected_spans
conflicted_spans
affected_traces
errors, bounded
```

The OTLP HTTP response follows protocol-compatible partial-success behavior while server
logs keep protected diagnostic detail.

## Merge and Deduplication

For every normalized span:

1. derive identity from source Trace ID and source Span ID;
2. combine it with canonical Run and Case identity;
3. calculate canonical content hash excluding ingestion time and derived sequence;
4. if identity is absent, reject;
5. if identity is new, insert;
6. if identity exists with the same hash, count duplicate and do nothing;
7. if identity exists with a different hash, preserve the original, record conflict, and
   mark the canonical Trace conflicted.

Never use last-write-wins for span identity conflicts.

Batch delivery order and retry count must not affect canonical content.

## Deterministic Global Ordering

`TraceSpan.sequence` is computed after merging all accepted spans. It is never copied
from request-array position.

Ordering key:

```text
1. turn_index, missing turns after known ordered turns
2. invocation attempt
3. start_time_unix_nano, missing timestamp after present timestamp
4. parent-before-child topological depth within one source trace
5. end_time_unix_nano
6. source_trace_id
7. source_span_id
```

Rules:

- parent appears before child when both are present;
- cycles or impossible parent graphs mark ordering degradation/conflict;
- missing parents are allowed for partial telemetry and recorded;
- missing timestamps use deterministic identity fallback, never ingestion time;
- sequence is reassigned densely from zero after every accepted merge;
- reconstructing from the same normalized spans always produces the same order.

Evaluator failure attribution may use sequence only from the canonical Trace used for that
evaluation.

## Completeness

### TraceCompletenessPolicy

The Run snapshots a policy such as:

```text
expected_turn_count
require_execution_result
require_terminal_signal
require_final_output
require_final_state
quiet_period_ms
deadline_seconds
late_arrival_policy
```

POC defaults:

- inline Demo/Python Trace may be complete immediately after validation;
- OTLP Trace requires target execution completion plus terminal signal or explicit
  complete marker;
- all expected turns must have completed records;
- no evaluator runs while status is `collecting`;
- no evaluator runs while status is `conflicted`;
- deadline expiration produces `incomplete`, not an empty complete Trace.

### Completion Marker

An explicit semantic terminal span/event may include:

```text
agentgate.trace.complete = true
agentgate.turn.complete = true
```

The marker is accepted only when correlation and invocation identity are valid.

### Incomplete Trace Policy

Default:

```text
incomplete Trace
  -> do not run content evaluators
  -> record Run/execution failure or review state
  -> preserve partial Trace for debugging
```

Do not convert missing telemetry into an Agent quality FAIL unless a separately configured
telemetry-completeness evaluator explicitly measures that contract.

## Late Arrivals

Before Results exist:

- accept valid late spans;
- rebuild ordering and content hash;
- re-evaluate completeness.

After Results exist:

- preserve the evaluated Trace revision/hash;
- record new telemetry as a later Trace revision or late-arrival set;
- do not silently mutate evidence used by persisted Results;
- require explicit rerun/re-evaluation to produce new Results.

Every Result/report must be able to identify the canonical Trace content hash used during
evaluation.

## Persistence

Replace one mutable JSON row with normalized idempotent storage:

```text
trace_records
  id, run_id, case_id, status, revision, content_sha256,
  completed_at, updated_at, canonical_payload
  UNIQUE(run_id, case_id, revision)

trace_spans
  run_id, case_id, source_trace_id, source_span_id,
  content_sha256, payload, received_at
  UNIQUE(run_id, case_id, source_trace_id, source_span_id)

trace_conflicts
  id, run_id, case_id, source_trace_id, source_span_id,
  original_sha256, conflicting_sha256, received_at, summary

trace_batches
  id, content_sha256, source, received_at,
  accepted_count, duplicate_count, rejected_count, conflict_count
```

If multi-tenant ingestion is added, tenant identity becomes part of every unique key.
Including Run/Case already permits intentional trace-only replay of the same source Trace
without weakening deduplication inside one evaluation.

Raw OTLP payload retention is disabled by default. Store batch hash and bounded metadata.
Optional raw diagnostics require explicit configuration, encryption, size/retention
limits, and access controls.

All span insertion, conflict recording, and canonical Trace revision creation happen in
one transaction per affected Run/Case where supported.

The current traces table is incompatible. POC migration policy:

- bump an explicit database schema version;
- reject startup against an unsupported old Trace schema with a clear reset/migration
  message;
- do not silently reinterpret old JSON documents;
- keep Dataset migration decisions independent.

## Receiver and API Behavior

Initial endpoint remains:

```text
POST /v1/traces
Content-Type: application/x-protobuf   primary SDK path
Content-Type: application/json         secondary debug/test path
```

Server responsibilities:

- authenticate/authorize when platform integration is enabled;
- enforce body-size and request timeout;
- delegate decoding and ingestion;
- return protocol-compatible success/partial success;
- never build canonical Trace logic in the FastAPI route.

Health remains:

```text
GET /health
```

Do not use `GET /v1/traces` as receiver health.

Internal debugging APIs may expose canonical Trace status and bounded conflicts, but not
raw unredacted telemetry.

## Security and Resource Limits

- authenticate production ingestion;
- verify Run/Case membership before persistence;
- reject arbitrary fallback identities;
- cap request bytes, spans per request, attributes per span, events, links, nesting,
  string length, and total normalized bytes;
- redact credentials and sensitive headers;
- reject or hash forbidden high-risk attributes according to configuration;
- do not deserialize executable objects;
- do not fetch links or references found in telemetry;
- protect against decompression bombs when compression is added;
- rate-limit orphan/conflicting telemetry;
- bound quarantine and conflict retention;
- avoid logging full Prompt, input, output, state, or attributes by default.

## Error Semantics

| Condition | Handling |
| --- | --- |
| malformed request root | reject request |
| unsupported content type | reject request |
| invalid individual span | partial rejection |
| missing Run/Case correlation | reject/quarantine as orphan |
| unknown Run/Case | reject/quarantine as orphan |
| conflicting canonical/legacy IDs | reject span and record conflict |
| exact duplicate span | accept idempotently as duplicate |
| same span ID with different content | preserve original, record conflict |
| missing parent span | accept as partial evidence |
| invalid parent cycle | mark conflicted/degraded |
| deadline without terminal evidence | mark incomplete |
| late span after evaluation | create later revision; do not mutate Results |
| repository failure | fail ingestion transaction; retryable transport error |

Telemetry ingestion failures are not evaluator ERRORs unless the evaluator itself fails
while consuming an already accepted canonical Trace.

## Rules to Avoid Design Drift

1. Do not map missing correlation to a shared fallback Run or Case.
2. Do not equate one OTLP source Trace ID with one AgentGate canonical Trace.
3. Do not replace a complete Run/Case Trace with the newest batch.
4. Do not assign sequence from request or arrival order.
5. Do not use ingestion timestamp as a deterministic ordering fallback.
6. Do not resolve span conflicts with last-write-wins.
7. Do not overwrite Results when late telemetry arrives.
8. Do not let evaluators parse OTLP or provider-specific payloads.
9. Do not infer tool/routing/state semantics from arbitrary span names.
10. Do not guess final output/state from generic attributes.
11. Do not treat incomplete telemetry as an Agent quality failure by default.
12. Do not persist raw telemetry indefinitely or by default.
13. Do not expose full telemetry or conflicts through public errors/logs.
14. Do not implement target invocation inside Trace receivers.
15. Do not implement optimizer/root-cause logic inside Trace normalization.
16. Keep source identity, canonical identity, revision, and content hash distinct.

## Parallel Development Boundary

```text
Trace owner
  domain/trace.py
  trace/
  Trace persistence methods/tables
  Trace-focused tests

Target owner
  domain/target.py
  run/targets/
  correlation emission

Dataset owner
  domain/case.py
  case/
  Dataset persistence/API/UI

Shared integration files
  storage/base.py
  storage/sqlite.py
  run/core.py
  server/application.py
  domain/__init__.py
```

Implement normalizer, merge service, and tests in a separate worktree. Change shared
storage/Run/API files only after the Dataset and Target contract checkpoints merge.

## Code Change Map

Status labels:

- `[ADD]` create;
- `[MOD]` modify;
- `[DEL]` delete;
- `[KEEP]` reuse without modification;
- `[DEFER]` retain boundary for later.

```text
agentgate-goal/
├── pyproject.toml                         [MOD] Add OTLP protobuf decoder dependency
│
├── src/agentgate/
│   ├── domain/
│   │   ├── __init__.py                       [MOD] Export expanded Trace contracts
│   │   ├── trace.py                          [MOD] Status, identities, turns, hash, revision
│   │   ├── result.py                         [MOD] Record evaluated Trace hash/revision
│   │   └── run.py                            [MOD] Snapshot TraceCompletenessPolicy
│   │
│   ├── trace/
│   │   ├── __init__.py                       [MOD] Export Trace service API
│   │   ├── models.py                         [MOD] Batch, normalized signal, report, conflict
│   │   ├── normalizer.py                     [MOD] Full IDs/timestamps/correlation/AnyValue
│   │   ├── ordering.py                       [ADD] Deterministic topology/time ordering
│   │   ├── merge.py                          [ADD] Dedupe, conflict, output/state precedence
│   │   ├── completeness.py                   [ADD] Policy evaluation
│   │   ├── service.py                        [ADD] Transactional ingestion orchestration
│   │   ├── evidence.py                       [MOD] Stable canonical span references
│   │   ├── receivers/
│   │   │   ├── __init__.py                   [MOD] Export receiver/report
│   │   │   ├── otlp_http.py                  [MOD] Protobuf/JSON decode, limits, partial success
│   │   │   └── otlp_grpc.py                  [DEFER] gRPC transport
│   │   └── importers/
│   │       ├── otlp.py                       [DEFER] Offline OTLP file import
│   │       ├── jaeger.py                     [DEFER] Jaeger import
│   │       └── json_trace.py                 [DEFER] Canonical JSON import
│   │
│   ├── storage/
│   │   ├── base.py                           [MOD] Batch/span/conflict/revision contracts
│   │   └── sqlite.py                         [MOD] Idempotent Trace tables and transactions
│   │
│   ├── run/
│   │   ├── core.py                           [MOD] Wait for complete Trace before evaluation
│   │   └── lifecycle.py                      [MOD] Trace wait/deadline/late state
│   │
│   ├── server/
│   │   └── application.py                    [MOD] Bounded OTLP receiver delegation
│   │
│   ├── evaluator/                            [KEEP] Consume canonical Trace
│   └── result/                               [KEEP] Aggregate persisted Results
│
├── tests/
│   ├── test_trace_models.py                  [ADD] Identity/status/hash validation
│   ├── test_otlp_normalizer.py               [ADD] IDs, timestamps, attributes, aliases
│   ├── test_trace_merge.py                   [ADD] Batches, duplicates, conflicts, signals
│   ├── test_trace_ordering.py                [ADD] Arrival-order independence and topology
│   ├── test_trace_completeness.py            [ADD] Inline/OTLP/turn/deadline policies
│   ├── test_trace_repository.py              [ADD] Transactions, uniqueness, reconstruction
│   ├── test_trace_late_arrival.py            [ADD] Revisions and immutable Result evidence
│   ├── test_otlp_http.py                     [MOD] Protobuf/JSON, limits, partial success
│   ├── test_otel_demo_export.py              [ADD] Standard Python SDK exporter integration
│   ├── test_demo_engine.py                   [MOD] Inline Trace still evaluates
│   ├── test_api.py                           [MOD] Trace status/revision response
│   └── test_snapshot_immutability.py         [MOD] Completeness policy affects Run hash
│
└── docs/
    ├── trace/README.md                       [MOD] Link this plan
    ├── trace/ingestion-plan.md               [ADD] This document
    ├── progress.md                           [MOD] Only after verification
    └── capability-mapping.md                 [MOD] Only after acceptance
```

No source file is deleted. The current mutable traces table is replaced through an
explicit database schema change.

## Delivery Checkpoints

### 1. Correlation and Normalization

- canonical and legacy attribute handling;
- strict Run/Case validation;
- source IDs, timestamps, and semantic kind normalization;
- no fallback identities;
- focused parser tests.

### 2. Merge and Ordering

- normalized span identity/hash;
- idempotent duplicate handling;
- conflict recording;
- deterministic global ordering independent of delivery order;
- canonical Trace ID and hash.

### 3. Persistence

- normalized span, batch, conflict, and Trace revision tables;
- transactional merge;
- deterministic reconstruction after restart;
- explicit incompatible-schema startup behavior.

### 4. Completeness and Run Integration

- snapshotted completeness policy;
- inline and OTLP completion;
- turn and invocation checks;
- deadline and incomplete behavior;
- evaluators run only on eligible canonical Trace.

### 5. Receiver and Late Arrivals

- bounded OTLP/HTTP protobuf and JSON partial-success response;
- standard Python OTLP HTTP exporter compatibility;
- late-arrival revisions;
- persisted Results retain evaluated Trace hash;
- protected conflict/debug visibility.

## Acceptance Tests

At minimum:

1. missing Run/Case correlation is never assigned a fallback identity;
2. canonical dotted attributes normalize correctly;
3. legacy aliases work only when non-conflicting;
4. conflicting canonical/legacy attributes reject the span;
5. invalid source Trace/Span IDs are rejected;
6. OTLP timestamps and nested AnyValues normalize correctly;
7. the same batch delivered twice produces one stored span;
8. overlapping batches merge without data loss;
9. same span identity/content is counted as duplicate;
10. same span identity/different content creates a conflict without overwrite;
11. canonical Trace aggregates multiple source Trace IDs for one Run Case;
12. different batch arrival orders produce identical span sequence and Trace hash;
13. parent precedes child when both are present;
14. missing parent remains valid partial telemetry;
15. cycle or impossible graph is reported deterministically;
16. output/state precedence does not depend on arrival order;
17. equal-precedence output conflict marks Trace conflicted;
18. inline Demo Trace can complete immediately;
19. OTLP Trace remains collecting until required completion evidence;
20. missing expected turn makes Trace incomplete;
21. deadline produces incomplete status without synthetic empty success;
22. evaluators do not run against collecting/incomplete Trace by default;
23. late telemetry before evaluation updates the canonical Trace;
24. late telemetry after evaluation creates a new revision;
25. persisted Result identifies the exact Trace revision/hash evaluated;
26. repository reconstruction after restart is deterministic;
27. request/span/attribute size limits are enforced;
28. partial success reports accepted and rejected counts;
29. raw sensitive telemetry is not logged or retained by default;
30. existing risky/fixed Demo evaluation outcomes remain unchanged.
31. the standard Python OTLP HTTP exporter can send Demo Agent spans without a custom
    exporter.

End-to-end acceptance:

```text
launch one external target Case
  -> propagate Run/Case/invocation correlation
  -> receive root span in OTLP batch A
  -> receive tool spans in batch B
  -> receive duplicate batch B
  -> receive terminal span in batch C
  -> build one complete canonical Trace
  -> evaluate once using stable sequence and Trace hash
  -> restart service and reconstruct identical Trace
```

## Deferred Work

- OTLP/gRPC receiver;
- Jaeger and vendor-specific importers;
- raw payload archive service;
- distributed ingestion workers;
- cross-region ordering;
- multi-tenant storage keys and retention;
- visual Trace graph redesign;
- trace-based optimizer/root-cause implementation;
- production metrics/alerts for ingestion SLOs.
