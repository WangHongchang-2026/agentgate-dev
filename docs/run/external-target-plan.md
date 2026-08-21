# External Target Integration Plan

## Goal

Define how AgentGate discovers, snapshots, and executes externally owned Agent and Skill
versions without becoming their asset-management system.

The core relationship is:

```text
External Agent Platform
        |
        v
Target metadata/version adapter
        |
        v
TargetSnapshot
        |
        +--> Run execution
        +--> Trace correlation
        +--> Dataset generation
        +--> Static Skill analysis
```

In AgentGate, `Target` means an invocable object being evaluated. It does not mean only
Agent:

```text
Target
├── Agent
└── Skill
```

The first production integration must allow the current Demo flow and one fake external
HTTP platform to use the same public contracts.

## Current State and Gap

Implemented:

- `Run` and immutable `RunSnapshot`;
- a minimal `TargetSnapshot` containing name, version, provider, and generic config;
- a `Target` Protocol embedded in `run/core.py`;
- synchronous `LocalScheduler` and `ExternalSchedulerAdapter` boundary;
- `PythonFunctionTarget`;
- deterministic loan Demo Agent with risky and fixed versions;
- optional OpenAI-compatible provider used inside the Demo;
- canonical Trace, evaluators, Results, persistence, CLI, API, and Web flow.

Current gaps:

- `TargetSnapshot` has no Target type or external object/version identity;
- `RunEngine` hard-codes `name="loan-agent"`;
- target version is passed separately from the target object and snapshot;
- `run/targets/base.py`, `http.py`, `process.py`, `python_fn.py`, and
  `trace_only.py` are empty;
- there is no adapter for listing Agent/Skill objects or versions;
- there is no normalized metadata contract for Dataset generation or Skill analysis;
- there is no request/response contract for invoking an external target;
- credentials, endpoint configuration, timeout, retry, cancellation, and idempotency are
  not modeled;
- Trace correlation assumes the target directly returns a canonical Trace;
- Demo provider and production target integration boundaries are mixed.

## Scope

This increment defines and implements:

1. Target terminology and immutable domain contracts.
2. A metadata/version catalog adapter.
3. A target execution adapter.
4. Demo and Python adapters using the new contracts.
5. An HTTP adapter tested against a fake external platform.
6. A trace-only adapter for evaluating existing telemetry without invoking a target.
7. explicit Run, Case, Turn, idempotency, and Trace correlation data.
8. target-related validation, errors, tests, and documentation.

## Non-Goals

- creating, editing, publishing, or deleting external Agent/Skill assets;
- owning AgentVersion or SkillVersion lifecycle;
- implementing a production credential vault;
- implementing the external Java scheduler;
- OTLP batch merge, deduplication, or persistence semantics;
- Dataset generation itself;
- static Skill analysis itself;
- LLM Judge provider execution;
- automatic retries inside every adapter;
- provider-specific SDKs beyond the first generic HTTP contract;
- Web target-management screens.

The target plan supplies contracts consumed by those later modules.

## Terms

### Target

The Agent or Skill selected for evaluation. A Target is an AgentGate abstraction over an
externally owned invocable object.

### TargetType

The product-level target category:

```text
agent
skill
```

Workflow, graph, chat agent, and other implementation styles are external-platform
details. They may appear in metadata but do not become additional P1 TargetTypes.

### External Agent Platform

The system that owns Agent, Skill, version, Prompt, tool, and invocation configuration.
AgentGate reads and invokes these assets through adapters.

### TargetRef

A stable reference to one exact external Target version:

```text
platform_id
target_type
external_target_id
external_version_id
```

A display name is not identity.

### TargetDescriptor

Normalized metadata read from the external platform for authoring workflows. It may
include descriptions, Prompt content or references, Skill summaries, tools, and I/O
schemas.

TargetDescriptor is used by Dataset generation and static Skill analysis. It is not
automatically embedded in every Run.

### TargetSnapshot

The immutable, evaluation-time record stored in RunSnapshot. It identifies exactly what
was invoked and contains only the metadata required for execution, audit, and
reproducibility.

### TargetCatalogAdapter

A read-only adapter that lists and resolves external Targets and versions into normalized
TargetDescriptor data.

### TargetExecutionAdapter

An adapter that invokes one exact TargetRef using a normalized execution request and
returns a normalized execution result.

### CredentialRef

An opaque identifier resolved by a credential boundary at execution time. It is never a
secret value and may be stored in configuration or snapshots.

### Invocation

One attempt to execute one Case turn against one Target version.

### Execution Result

The immediate normalized response from target invocation. It contains target output,
state, execution identity, and telemetry correlation information. It is not an
Evaluator Result.

### Trace Correlation

The identifiers and W3C trace context that allow telemetry arriving separately from the
execution response to be associated with the correct Run, Case, and optional turn.

### Trace-Only Target

A target mode that does not invoke an Agent/Skill. It evaluates an already stored or
imported canonical Trace.

## Ownership Boundaries

```text
external platform
  owns Agent, Skill, versions, Prompt, tools, endpoint, deployment

domain/target.py
  owns TargetRef, descriptors, snapshots, requests, responses, and errors

run/targets/
  owns catalog and execution adapter behavior

run/
  owns orchestration, lifecycle, retry policy, and scheduler interaction

trace/
  owns telemetry receivers, normalization, merge, and canonical Trace

case/
  owns Case input and expectations; does not invoke targets

control_plane/
  selects a Target and Dataset and starts a Run

server/cli/web
  present workflows; do not implement adapter rules
```

## Architecture

### Metadata Path

```text
External Platform API
        |
        v
TargetCatalogAdapter
        |
        +--> list_targets(type, cursor, filters)
        +--> list_versions(Target identity)
        +--> get_descriptor(TargetRef)
        |
        v
TargetDescriptor
        |
        +--> TargetSnapshotFactory --> RunSnapshot
        +--> Dataset generator
        +--> Static Skill analyzer
```

### Execution Path

```text
RunEngine
   |
   v
TargetExecutionRequest
   |
   v
TargetExecutionAdapter
   |
   +--> demo
   +--> python function
   +--> HTTP
   +--> process
   +--> trace only
   |
   v
TargetExecutionResult
   |
   +--> immediate output/final state
   +--> inline Trace, when available
   +--> external execution ID
   +--> telemetry correlation reference
   |
   v
canonical Trace -> Evaluators
```

## Domain Model

Add `src/agentgate/domain/target.py`.

### TargetType

```python
class TargetType(StrEnum):
    AGENT = "agent"
    SKILL = "skill"
```

### TargetRef

```python
class TargetRef(DomainModel):
    platform_id: str
    target_type: TargetType
    external_target_id: str
    external_version_id: str
```

All fields are required and non-empty. The tuple of all four fields is the external
identity. AgentGate may calculate a stable internal key from their canonical JSON, but it
must retain the original values.

### ToolDescriptor

```python
class ToolDescriptor(DomainModel):
    name: str
    description: str | None
    input_schema: FrozenJsonObject
```

### SkillDescriptor

```python
class SkillDescriptor(DomainModel):
    external_skill_id: str
    external_version_id: str
    name: str
    description: str | None
    prompt: str | None
    tools: tuple[ToolDescriptor, ...]
```

### TargetDescriptor

```python
class TargetDescriptor(DomainModel):
    ref: TargetRef
    display_name: str
    description: str | None
    prompt: str | None
    skills: tuple[SkillDescriptor, ...]
    tools: tuple[ToolDescriptor, ...]
    input_schema: FrozenJsonObject
    output_schema: FrozenJsonObject
    metadata: FrozenJsonObject
    fetched_at: datetime
    content_sha256: str
```

For a Skill target, `skills` is empty and its own Prompt/tools use the top-level fields.
For an Agent target, `skills` contains the normalized routable Skill summaries supplied
by the external platform.

Prompt content is optional because platform policy may expose only a reference or hash.
Generation and analysis must report insufficient input rather than invent unavailable
metadata.

### TargetSnapshot

Move the current type from `domain/run.py` to `domain/target.py` and replace its fields:

```python
class TargetSnapshot(DomainModel):
    ref: TargetRef
    display_name: str
    adapter_type: str
    adapter_version: str
    descriptor_sha256: str
    invocation_config: FrozenJsonObject
    credential_ref: str | None
    captured_at: datetime
    content_sha256: str
```

Rules:

- no plaintext credential;
- no mutable endpoint-discovery result that cannot be reproduced;
- adapter type and version are mandatory;
- invocation configuration contains normalized non-secret configuration;
- content hash covers every field except itself;
- RunSnapshot embeds the complete TargetSnapshot.

### TargetExecutionRequest

```python
class TargetExecutionRequest(DomainModel):
    invocation_id: str
    idempotency_key: str
    run_id: str
    case_id: str
    turn_id: str | None
    target: TargetSnapshot
    input: FrozenJsonObject
    state: FrozenJsonObject
    timeout_seconds: float
    traceparent: str
    baggage: str | None
```

The same retry of one logical invocation reuses `idempotency_key`. A new attempt receives
a new invocation ID but retains its logical idempotency key.

### TargetExecutionResult

```python
class TargetExecutionResult(DomainModel):
    invocation_id: str
    external_execution_id: str | None
    output: FrozenJsonValue
    final_state: FrozenJsonObject
    inline_trace: Trace | None
    trace_id: str | None
    completed_at: datetime
```

Inline Trace supports Demo, Python, and process adapters. External HTTP targets may emit
OTLP separately and return only correlation data.

Do not name this object `Result`; that name belongs to evaluator output.

## Adapter Protocols

### TargetCatalogAdapter

```python
class TargetCatalogAdapter(Protocol):
    adapter_type: str
    adapter_version: str

    def list_targets(...) -> TargetPage: ...
    def list_versions(...) -> TargetVersionPage: ...
    def get_descriptor(self, ref: TargetRef) -> TargetDescriptor: ...
```

Catalog methods are read-only. They do not create or update external assets.

### TargetExecutionAdapter

```python
class TargetExecutionAdapter(Protocol):
    adapter_type: str
    adapter_version: str

    def execute(self, request: TargetExecutionRequest) -> TargetExecutionResult: ...
```

Adapters receive a fully resolved snapshot. They must not silently replace the requested
external version with “latest”.

### CredentialResolver

```python
class CredentialResolver(Protocol):
    def resolve(self, credential_ref: str) -> ResolvedCredential: ...
```

This plan defines the boundary only. Production encryption/storage belongs to the future
credential plan. Resolved secrets stay in process memory and never enter domain models,
Trace attributes, logs, or exceptions.

## Adapter Types

### Demo Adapter

- wraps the current loan Demo Agent;
- exposes risky and fixed versions through TargetRef;
- keeps an inline canonical Trace mode only for focused unit tests;
- invokes the instrumented Demo Agent HTTP service for end-to-end acceptance;
- the HTTP Demo Agent records behavior with the OpenTelemetry SDK and exports standard
  OTLP/HTTP protobuf to AgentGate;
- remains deterministic and requires no credential;
- proves the same public target and telemetry contracts without an external platform.

The Demo Agent instrumentation and service are specified separately in
`docs/run/demo-agent-plan.md`.

### Python Function Adapter

- invokes an explicitly registered callable;
- does not import arbitrary code from Dataset content;
- receives normalized request data;
- returns output/state and optional inline Trace;
- is primarily for tests and trusted local integrations.

### HTTP Adapter

- invokes a configured external endpoint;
- uses CredentialRef resolution;
- sends stable request and correlation fields;
- validates status code, content type, and response schema;
- does not assume OpenAI Chat Completions format;
- does not parse telemetry as evaluator evidence inside the adapter.

Initial HTTP request:

```json
{
  "invocation_id": "...",
  "idempotency_key": "...",
  "target": {
    "type": "agent",
    "id": "...",
    "version_id": "..."
  },
  "run_id": "...",
  "case_id": "...",
  "turn_id": null,
  "input": {},
  "state": {}
}
```

Correlation headers:

```text
traceparent
baggage
X-AgentGate-Run-Id
X-AgentGate-Case-Id
X-AgentGate-Turn-Id       only when present
Idempotency-Key
```

The external platform must echo `invocation_id` and should return an external execution
ID and Trace ID.

### Process Adapter

- executes an allowlisted executable and argument template;
- exchanges bounded JSON through stdin/stdout;
- applies timeout and output-size limits;
- captures sanitized stderr reference, not unrestricted stderr in API results;
- is deferred unless needed for an actual integration.

### Trace-Only Adapter

- does not invoke a target;
- resolves an existing canonical Trace by stable reference;
- verifies Run/Case compatibility;
- records that execution mode is `trace_only`;
- allows offline replay and demonstrations when the target endpoint is unavailable.

## Run Integration

Change RunEngine from:

```text
dataset + Target object + separate version string + provider
```

to:

```text
dataset version
+ TargetSnapshot
+ TargetExecutionAdapter
+ evaluator specifications
+ execution policy
```

Rules:

1. Resolve and validate the exact TargetRef before creating the Run.
2. Build TargetSnapshot once and include it in RunSnapshot.
3. Never reread “latest” target version during a running or historical Run.
4. Build one TargetExecutionRequest per Case turn.
5. Scheduler executes the request through the selected adapter.
6. Persist execution state before invocation.
7. Resolve an inline or separately ingested canonical Trace.
8. Start evaluator execution only when the Trace completeness policy is satisfied.
9. Keep target execution failures separate from evaluator ERRORs.

The current local synchronous scheduler remains valid for the POC. The external scheduler
later receives the same normalized execution request through its own adapter.

## Trace Correlation

Every invocation has:

```text
run_id
case_id
turn_id, optional until multi-turn execution
invocation_id
idempotency_key
W3C traceparent
```

Required OTLP resource/span attributes:

```text
agentgate.run.id
agentgate.case.id
agentgate.turn.id          when present
agentgate.invocation.id
agentgate.target.type
agentgate.target.id
agentgate.target.version
```

Target adapters create and propagate correlation context. The Trace module defines merge,
deduplication, ordering, and completeness semantics in
`docs/trace/ingestion-plan.md`.

Run completion and Trace completion are different:

```text
target response received
        |
        v
execution completed
        |
        v
wait for required Trace evidence
        |
        +--> complete -> evaluate
        +--> timeout  -> apply explicit incomplete-trace policy
```

Do not evaluate an empty synthetic Trace as if complete telemetry existed.

## Errors and Outcomes

Target integration errors are Run/execution errors, not evaluator Results:

| Error | Meaning | Retryable default |
| --- | --- | --- |
| `target_not_found` | external target ID does not exist | no |
| `version_not_found` | exact external version does not exist | no |
| `unauthorized` | credential rejected | no |
| `invalid_configuration` | snapshot/adapter configuration invalid | no |
| `rate_limited` | external platform throttled invocation | yes |
| `timeout` | invocation exceeded snapshotted timeout | policy |
| `unavailable` | endpoint temporarily unavailable | yes |
| `rejected` | platform refused valid request | no |
| `protocol_error` | malformed or incompatible response | no |
| `trace_timeout` | execution returned but required telemetry did not arrive | policy |

Rules:

- reject identity/configuration errors before execution when possible;
- sanitize public errors and retain full technical detail only in protected logs;
- do not convert target invocation errors into Agent FAIL;
- do not run content evaluators when no valid execution/Trace exists;
- retry policy belongs to Run/scheduler configuration, not hidden adapter loops.

## Timeout, Retry, Cancellation, and Idempotency

- timeout is snapshotted per Run;
- adapters receive the remaining deadline, not a fresh unbounded timeout;
- scheduler owns retry count and backoff;
- retryable error classification comes from the adapter;
- every logical Case-turn invocation has an idempotency key;
- cancellation is propagated when supported;
- lack of remote cancellation support must be reported explicitly;
- late responses and telemetry from cancelled attempts remain auditable but cannot be
  attached to a different attempt.

## Security and Data Handling

- persist CredentialRef only, never a secret;
- redact Authorization, cookies, tokens, passwords, and private headers;
- allowlist endpoint schemes and enforce deployment network policy;
- do not permit Dataset content to choose arbitrary URLs, executables, or Python imports;
- bound metadata, response, stdout/stderr, and Trace-reference sizes;
- treat external Prompt, description, tools, input, output, and state as potentially
  sensitive;
- make TargetDescriptor persistence explicit rather than automatic;
- record descriptor and snapshot hashes for audit;
- do not include complete target metadata in error messages.

## API Boundary

The application service eventually exposes:

```text
GET /api/targets?type=agent|skill
GET /api/targets/{type}/{target_id}/versions
GET /api/targets/{type}/{target_id}/versions/{version_id}
POST /api/runs
```

Run creation references:

```json
{
  "target": {
    "platform_id": "external-platform",
    "target_type": "agent",
    "external_target_id": "agent-123",
    "external_version_id": "version-7"
  },
  "dataset_id": "dataset-1",
  "dataset_version": 3,
  "evaluator_ids": ["..."]
}
```

FastAPI delegates to a target application service and RunEngine. Routes must not call an
external platform directly.

The first implementation may expose Demo targets only in the UI while verifying the HTTP
adapter through integration tests.

## Rules to Avoid Design Drift

1. Target means Agent or Skill; do not use Target as a synonym for Agent only.
2. Do not model externally owned Agent/Skill CRUD inside AgentGate.
3. Do not identify a Target by display name or mutable “latest” alias.
4. Do not pass target version separately from the immutable TargetSnapshot.
5. Do not place plaintext credentials in TargetSnapshot, RunSnapshot, Trace, or Result.
6. Do not let Dataset fields select arbitrary endpoints, commands, or Python functions.
7. Do not hide retries inside adapters.
8. Do not let adapters silently fall back to another target version.
9. Do not convert invocation errors into evaluator FAIL.
10. Do not implement Trace merge/deduplication inside HTTP or Demo adapters.
11. Do not require external platforms to return a canonical AgentGate Trace directly.
12. Do not persist rich TargetDescriptor data unless a declared workflow requires it.
13. Do not make Dataset generation or Skill analysis fetch external data independently;
    both consume TargetCatalogAdapter contracts.
14. Do not duplicate target selection rules in CLI, FastAPI, and Vue.
15. Keep Demo-only behavior under `demo/` or a Demo adapter.

## Parallel Development Boundary

This plan may be written while Dataset/Case work continues. Implementation must use a
separate branch and worktree.

```text
Target integration owner
  domain/target.py
  run/targets/
  target-focused tests

Dataset owner
  domain/case.py
  case/
  Dataset persistence/API/UI

Shared integration files
  domain/run.py
  run/core.py
  control_plane/service.py
  server/application.py
  web target selector
```

Implement isolated target domain/adapters first. Modify shared integration files only
after the Dataset branch is merged or after an explicit shared-contract checkpoint.

## Code Change Map

Status labels:

- `[ADD]`: create;
- `[MOD]`: modify;
- `[DEL]`: delete;
- `[KEEP]`: explicitly reuse without modification;
- `[DEFER]`: reserved but not implemented in this increment.

```text
agentgate-goal/
├── src/agentgate/
│   ├── domain/
│   │   ├── __init__.py                    [MOD] Export target contracts
│   │   ├── target.py                      [ADD] Target types, refs, descriptors, snapshots,
│   │   │                                        requests, responses, and errors
│   │   └── run.py                         [MOD] Import TargetSnapshot; remove old minimal type
│   │
│   ├── run/
│   │   ├── core.py                        [MOD] Accept snapshot + adapter; remove hard-coded target
│   │   ├── lifecycle.py                   [MOD] Invocation and Trace-wait lifecycle
│   │   ├── snapshot.py                    [MOD] Build/validate TargetSnapshot
│   │   └── targets/
│   │       ├── __init__.py                [MOD] Export adapter API
│   │       ├── base.py                    [MOD] Catalog/execution/credential Protocols
│   │       ├── demo.py                    [ADD] Demo target catalog and execution
│   │       ├── http.py                    [MOD] Generic external HTTP adapter
│   │       ├── python_fn.py               [MOD] Trusted Python function adapter
│   │       ├── trace_only.py              [MOD] Existing Trace replay adapter
│   │       └── process.py                 [DEFER] Process adapter until required
│   │
│   ├── demo/
│   │   ├── loan.py                        [MOD] Expose Demo adapter-compatible versions
│   │   └── provider.py                    [MOD] Keep model provider internal to Demo target
│   │
│   ├── control_plane/
│   │   └── core.py                        [MOD] Resolve target before launch; after Dataset merge
│   │
│   ├── server/
│   │   └── application.py                 [MOD] Target listing/detail and Run request
│   │
│   ├── trace/                             [KEEP] Consume correlation; ingestion plan owns changes
│   ├── evaluator/                         [KEEP] Consume canonical Trace only
│   ├── result/                            [KEEP] No target invocation behavior
│   └── storage/                           [KEEP] Snapshot persists inside current Run payload
│
├── tests/
│   ├── test_target_models.py              [ADD] Identity, immutability, hashes, secret exclusion
│   ├── test_target_snapshot.py            [ADD] Descriptor-to-snapshot rules
│   ├── test_demo_target.py                [ADD] Risky/fixed Demo through common adapter
│   ├── test_python_target.py              [MOD] New normalized request/result contract
│   ├── test_http_target.py                [ADD] Fake external catalog/invocation server
│   ├── test_trace_only_target.py          [ADD] Replay identity validation
│   ├── test_target_errors.py              [ADD] Error taxonomy and redaction
│   ├── test_demo_engine.py                [MOD] Run uses TargetSnapshot without hard-coding
│   ├── test_api.py                        [MOD] Target refs in Run launch
│   └── test_snapshot_immutability.py      [MOD] Target snapshot affects Run hash
│
└── docs/
    ├── run/README.md                      [MOD] Link this plan
    ├── run/external-target-plan.md        [ADD] This document
    ├── progress.md                        [MOD] Only after verified implementation
    └── capability-mapping.md              [MOD] Only after acceptance passes
```

No source file is deleted in this increment. The old TargetSnapshot definition is moved,
not retained as a compatibility duplicate.

## Delivery Checkpoints

### 1. Domain Contracts

- add TargetType, TargetRef, TargetDescriptor, TargetSnapshot, request, and result;
- enforce non-empty exact version identity;
- enforce deep immutability and canonical hashes;
- prove secrets cannot enter snapshot fields.

### 2. Adapter Interfaces and Demo

- define catalog and execution Protocols;
- implement Demo catalog/execution adapter;
- migrate risky/fixed Demo versions without changing outcomes;
- move Python function execution under `run/targets/`.

### 3. HTTP Integration

- implement generic HTTP catalog/invocation adapter;
- add correlation and idempotency headers;
- validate bounded response schema;
- classify and sanitize external errors;
- verify with a fake external platform.

### 4. Run Integration

- remove hard-coded target name/version/provider;
- resolve one TargetRef into one TargetSnapshot before Run creation;
- execute normalized requests;
- support inline Trace and external Trace references;
- retain existing local scheduler.

### 5. Application/API Integration

- list Demo targets and versions through the catalog contract;
- launch a Run with exact TargetRef;
- keep existing Dataset selection working;
- update CLI/API/Web types only after shared Dataset integration is stable.

## Acceptance Tests

At minimum:

1. TargetType accepts Agent and Skill and rejects unknown values.
2. Target identity requires platform, type, object ID, and exact version ID.
3. TargetSnapshot is deeply immutable and content-hashed.
4. Changing target version, adapter version, or invocation config changes RunSnapshot
   hash.
5. TargetSnapshot cannot serialize a plaintext credential field.
6. Catalog adapter lists Agent and Skill versions with stable pagination.
7. Descriptor hash changes when Prompt, description, Skill, tool, or schema changes.
8. Missing Prompt metadata is represented as unavailable, not invented.
9. Demo risky and fixed versions retain current Gate outcomes.
10. The end-to-end Demo path uses HTTP invocation and real OTel SDK export rather than a
    manually constructed canonical Trace.
11. Python function adapter uses the normalized request/result contract.
12. HTTP adapter invokes the exact external version.
13. HTTP adapter sends Run/Case/Turn, idempotency, and W3C correlation.
14. Adapter rejects malformed content type or response shape.
15. 401, 404, 429, timeout, and 5xx map to the declared error taxonomy.
16. Public errors and logs redact credentials.
17. Retry reuses the idempotency key and does not silently change version.
18. Trace-only mode does not invoke a target.
19. An inline Trace must match the request Run/Case/Turn identity.
20. A separately emitted Trace can be correlated by invocation identity.
21. Target invocation error stops evaluation and never becomes Agent FAIL.

End-to-end acceptance:

```text
List targets from fake external platform
  -> select exact Agent or Skill version
  -> build immutable TargetSnapshot
  -> launch Run with published DatasetVersion
  -> invoke target using correlation/idempotency context
  -> obtain or await canonical Trace
  -> evaluate and persist report
  -> inspect RunSnapshot and resolve exact external identity
```

## Deferred Work

- production credential storage and encryption: `docs/security/credentials-plan.md`;
- external Java scheduler: `docs/queue/scheduler-adapter-plan.md`;
- OTLP merge/deduplication: `docs/trace/ingestion-plan.md`;
- Dataset generation: `docs/dataset/generation-plan.md`;
- static Skill analysis: `docs/analysis/skill-static-analysis-plan.md`;
- production platform-specific adapters;
- process execution unless an actual integration requires it;
- Target management UI;
- multi-tenant authorization;
- automatic external Agent mutation.
