# Lineage Query And Visualization Implementation Plan

Last updated: 2026-09-08

## 1. Purpose

AgentGate must preserve and visualize the exact version relationships behind an
Evaluation Run. Users must be able to start from a Run, Dataset version, Case content
version, Agent version, Skill version, Evaluator version, or A/B Test and see the related
evaluation records.

The graph is evidence derived from immutable records. It is not an independently editable
business object and must never be reconstructed from a customer's mutable `latest`
metadata.

## 2. Required Relationships

```text
                             A/B Test
                       +---------+---------+
                       |                   |
                 baseline Run       candidate Run
                       |                   |
          +------------+------+     +------+------------+
          |            |      |     |      |            |
          v            v      v     v      v            v
     Dataset v3   Agent v1  Evaluators  Agent v2   Evaluators
          |            |                       |
          v            v                       v
     Case versions  Skill versions         Skill versions
```

The Dataset-to-Agent relationship is always mediated by a Run:

```text
DatasetVersion <- used by - EvaluationRun - evaluates -> TargetVersion
```

| Source | Relationship | Target | Cardinality |
|---|---|---|---|
| A/B Test | `baseline_run` | Evaluation Run | exactly one |
| A/B Test | `candidate_run` | Evaluation Run | exactly one |
| Evaluation Run | `uses_dataset` | Dataset version | exactly one |
| Dataset version | `contains_case` | Case content version | one or more when published |
| Evaluation Run | `evaluates_agent` | Agent version | zero or one |
| Evaluation Run | `evaluates_skill` | Skill version | zero or one |
| Agent descriptor | `includes_skill` | Skill version | zero or more |
| Evaluation Run | `uses_evaluator` | Evaluator version | one or more |

Exactly one of `evaluates_agent` and `evaluates_skill` exists for each Run.

## 3. Authoritative Records

Lineage is reconstructed from four durable records.

```text
TargetDescriptor                  DatasetVersion
├── Agent/Skill exact reference   ├── exact version and hash
├── prompt hash                   └── immutable Cases
├── Skill versions
└── Tool/schema metadata
          ^
          | descriptor_sha256
          |
EvaluationRun / RunManifest       ABTest
├── TargetSnapshot                ├── baseline_run_id
├── DatasetVersion                └── candidate_run_id
├── EvaluatorSpecs
└── execution configuration
```

### `TargetDescriptor`

`TargetDescriptor` already exists in `domain/target.py`. It describes the exact Agent or
Skill version, including Agent Skills, Tools, schemas, prompt content/hash, and normalized
metadata.

It is currently only a tested model. Runtime code neither persists it nor uses it to
construct `TargetSnapshot`. This plan makes it a real runtime record.

### `TargetSnapshot`

`TargetSnapshot` remains the small execution snapshot stored in `RunManifest`. It records
the exact external Target version, adapter configuration, credential reference, and
`descriptor_sha256`.

Do not copy Skills into `TargetSnapshot`. Resolve them through its immutable descriptor
hash:

```text
RunManifest.target.descriptor_sha256
                   |
                   v
       persisted TargetDescriptor
                   |
                   v
             Skill versions
```

### Dataset and Cases

`RunManifest.dataset` embeds the complete published `DatasetVersion`, including ordered
Cases. The same Dataset version also remains in Dataset storage.

`Case` has no independent numeric revision. Its lineage version is:

```text
dataset_id + dataset_version + case_id + case_content_sha256
```

Do not add a second Case revision counter solely for lineage.

### Evaluators

`RunManifest.evaluator_specs` embeds each exact Evaluator version and content hash. No
lookup of the current evaluator catalog is required to reconstruct Run history.

### A/B Tests

An A/B Test is a focused persisted record:

```text
id
baseline_run_id
candidate_run_id
created_at
```

It references two ordinary Evaluation Runs and does not duplicate their Dataset, Target,
Skill, Evaluator, metric, or gate data. A/B status is derived from its Runs; comparison
results are produced by `result/comparison.py`.

## 4. Code Ownership

```text
src/agentgate/
├── domain/
│   ├── target.py                 # existing descriptor and snapshot contracts
│   └── ab_test.py                # focused immutable A/B Test record
├── application/
│   ├── target_catalog.py         # descriptor registration and exact resolution
│   ├── run_management.py         # validates descriptor before Run creation
│   ├── ab_testing.py             # creates/validates baseline and candidate Runs
│   └── lineage_queries.py        # graph read models and graph construction
├── storage/
│   ├── repository.py             # descriptor, A/B, and reverse-query contracts
│   └── sqlite.py                 # tables, transactions, and indexes
└── server/routes/
    └── lineage.py                # read-only lineage endpoints

web/src/
└── pages/LineagePage.vue         # graph/tree visualization
```

Do not create a top-level `lineage/` package. Current graph construction is a read-only
application workflow. Extract a package only when persisted graph storage, arbitrary
traversal, dependency-impact analysis, or reusable graph algorithms are required.

## 5. TargetDescriptor Lifecycle

### External mode

```text
Dify / Coze / customer platform
          |
          v
Target platform integration
          |
          v
normalized TargetDescriptor
          |
          v
TargetCatalog.register_descriptor()
          |
          +--> persist by content_sha256
          +--> resolve exact Agent/Skill version
          |
          v
TargetSnapshot(descriptor_sha256=descriptor.content_sha256)
```

### Demo mode

The demo bootstrap creates a real `TargetDescriptor` for each Loan Agent version,
including its demo Skills. It persists the descriptor before creating the associated
TargetSnapshot. CLI and FastAPI must stop hashing ad hoc dictionaries as fake descriptors.

### Storage contract

Add explicit repository operations:

```python
save_target_descriptor(descriptor: TargetDescriptor) -> None
get_target_descriptor(content_sha256: str) -> TargetDescriptor | None
list_target_descriptors(ref: TargetRef | None = None) -> list[TargetDescriptor]
```

Descriptors are content-addressed and immutable. Re-saving identical content is
idempotent. The same external version may produce a different descriptor hash if a vendor
mutates content in place; both records remain available so historical Runs stay valid.

### SQLite table

```sql
CREATE TABLE target_descriptors (
    content_sha256 TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    external_target_id TEXT NOT NULL,
    external_version_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX idx_target_descriptor_ref
ON target_descriptors(
    source_id, target_type, external_target_id, external_version_id
);
```

Prompts and metadata may contain customer business information. APIs and lineage graphs do
not return descriptor payloads unless a separately authorized Target-detail use case is
implemented. Existing credential-like field rejection remains mandatory.

## 6. Run Creation Contract

The caller selects references:

```json
{
  "target": {
    "source_id": "customer-platform",
    "target_type": "agent",
    "external_target_id": "loan-agent",
    "external_version_id": "v3"
  },
  "dataset_id": "loan-policy",
  "dataset_version": 5,
  "evaluator_ids": ["routing", "final-state"]
}
```

Application composition resolves immutable records before creating the Run:

```text
request
  -> exact DatasetVersion
  -> exact TargetDescriptor
  -> TargetSnapshot referencing descriptor hash
  -> exact EvaluatorSpecs
  -> immutable RunManifest
  -> persisted EvaluationRun
```

`RunManagement.create_run()` must verify:

- the descriptor exists in storage;
- `TargetSnapshot.descriptor_sha256` equals its content hash;
- descriptor and snapshot `TargetRef` values match exactly;
- the Dataset version is published;
- Evaluator versions are exact and valid.

Descriptor persistence and initial Run persistence must not leave a Run with a dangling
descriptor reference. Application orchestration should register the descriptor before Run
creation; repository constraints or transactional composition enforce the final boundary.

## 7. Lineage Read Models

`application/lineage_queries.py` defines transport-neutral read models, not new Domain
entities.

```python
LineageNodeKind = Literal[
    "run", "ab_test", "dataset", "case", "agent", "skill", "evaluator"
]

LineageRelation = Literal[
    "baseline_run",
    "candidate_run",
    "uses_dataset",
    "contains_case",
    "evaluates_agent",
    "evaluates_skill",
    "includes_skill",
    "uses_evaluator",
]

class LineageNode(BaseModel):
    id: str
    kind: LineageNodeKind
    external_id: str
    label: str
    version: str | None
    content_sha256: str | None

class LineageEdge(BaseModel):
    source_id: str
    target_id: str
    relation: LineageRelation

class LineageGraph(BaseModel):
    root_node_id: str
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdge, ...]
```

Invariants:

- node IDs and edge triples are unique;
- all edge endpoints exist;
- the root node exists;
- versioned executable assets expose exact versions;
- content hashes are included whenever their source record provides one.

Graph nodes deliberately omit prompts, Tool definitions, Case inputs, expectations,
invocation configuration, credential references, Traces, and Results.

## 8. Graph Construction Algorithm

Relationships are captured in immutable records at write time. `LineageGraph` is assembled
at query time and is never persisted.

Use:

```text
nodes_by_id: dict[str, LineageNode]
edges: set[tuple[source_id, target_id, relation]]
visited: set[str]
```

Private operations remain in `application/lineage_queries.py`:

```text
_add_node()
_add_edge()
_expand_run()
_expand_dataset()
_expand_target_descriptor()
_expand_ab_test()
```

Algorithm:

1. Load the root resource.
2. Add its node.
3. Follow only typed, approved relationships.
4. Resolve a Run's descriptor by `descriptor_sha256`.
5. Add Dataset Cases, Target Skills, and Evaluators.
6. For A/B, expand baseline and candidate Runs.
7. Deduplicate shared nodes and edges.
8. Sort output deterministically.

This is visited-set traversal with `O(V + E)` complexity. Do not add NetworkX, a graph
database, PageRank, shortest-path logic, or cycle algorithms.

### Stable node IDs

```text
run:{run_id}
ab_test:{ab_test_id}
dataset:{dataset_id}:{version}:{content_sha256}
case:{dataset_id}:{dataset_version}:{case_id}:{content_sha256}
target:{source_id}:{target_type}:{external_target_id}:{external_version_id}:{descriptor_sha256}
skill:{source_id}:{external_skill_id}:{external_version_id}:{content_sha256}
evaluator:{evaluator_id}:{version}:{content_sha256}
```

Use canonical hashing helpers for Case and Skill content. Never parse node IDs to recover
business data.

## 9. Reverse Lookup Index

Forward Run lineage needs `get_run()` and `get_target_descriptor()`. Reverse queries must
not scan only the latest 50 Runs or load every Run indefinitely.

Persist derived Run-to-asset references when a Run is first written:

```text
run_asset_refs
├── run_id
├── asset_kind
├── source_id
├── asset_id
├── version
└── content_sha256
```

References include the Run's Dataset, Cases, Target, descriptor Skills, and Evaluators.
They are written transactionally and can be rebuilt from RunManifest plus
TargetDescriptor. They accelerate queries but are not authoritative.

Expose explicit repository methods rather than a free-form SQL/query language:

```python
list_runs_by_dataset_version(dataset_id, version, limit)
list_runs_by_case_content(dataset_id, version, case_id, content_sha256, limit)
list_runs_by_target_version(source_id, target_type, target_id, version, limit)
list_runs_by_skill_version(source_id, skill_id, version, limit)
list_runs_by_evaluator_version(evaluator_id, version, limit)
list_ab_tests_by_run_ids(run_ids)
```

Storage-specific SQL stays in `storage/sqlite.py`.

## 10. HTTP API

Forward queries:

```http
GET /api/runs/{run_id}/lineage
GET /api/ab-tests/{ab_test_id}/lineage
```

Reverse queries:

```http
GET /api/datasets/{dataset_id}/versions/{version}/lineage
GET /api/datasets/{dataset_id}/versions/{version}/cases/{case_id}/lineage
GET /api/targets/{source_id}/{target_type}/{target_id}/versions/{version}/lineage
GET /api/skills/{source_id}/{skill_id}/versions/{version}/lineage
GET /api/evaluators/{evaluator_id}/versions/{version}/lineage
```

Behavior:

- unknown root records return `404`;
- a valid asset with no related Runs returns a graph containing only the root node;
- malformed versions and limits return `422`;
- graph construction failures caused by missing referenced immutable records return a
  sanitized `409`, because stored lineage is inconsistent;
- endpoints are read-only;
- output ordering is deterministic.

## 11. Web Visualization

`LineagePage.vue` consumes `LineageGraph`; it does not infer relationships.

Required interactions:

- Run-centered dependency tree;
- A/B baseline and candidate branches;
- shared Dataset/Evaluator nodes displayed once;
- filters by node kind;
- node selection showing ID, version, type, and hash;
- links to owning Run, Result, Dataset, Evaluator, or Target views;
- clear empty, loading, and failed states;
- usable desktop and mobile layouts.

Start with a deterministic DAG/tree layout. Add a proven Vue graph library only after the
plain layout cannot satisfy shared-node visualization and browser verification.

## 12. Source Assessment

### `goal/p1-demo`

- TargetDescriptor is not used by runtime code.
- `lineage/` and `experiment/` are one-line placeholders.
- No persistence, traversal, API, or visualization code is reusable.

### `team/integration-p1-new`

- Single-Case reruns record parent/root Run IDs, proving explicit Run relationships are
  useful.
- Its Target catalog uses mutable, untyped capability dictionaries and a separate model
  hierarchy.
- Its lineage, experiment, and comparison code is empty or coupled to the rejected broad
  Control Plane and obsolete RunSnapshot contracts.
- Reuse concepts only; do not copy code.

### Current refactor

Reuse directly:

- `TargetDescriptor`, `TargetSnapshot`, `RunManifest`, `DatasetVersion`, `Case`, and
  `EvaluatorSpec`;
- repository boundaries and SQLite transaction patterns;
- FastAPI dependency/error conventions;
- `result/comparison.py` for compatible Run comparison.

Write from scratch:

- TargetDescriptor storage and application catalog behavior;
- Run-to-descriptor validation;
- A/B Test persistence/application orchestration;
- reverse lookup indexes;
- graph read models, traversal, APIs, and Web visualization.

Reuse means adapting behavior to current contracts, not copying old files.

## 13. Implementation Sequence

Each file follows the project checkpoints: filename, responsibility, class/function
design, source assessment, explicit approval, implementation, and tests.

1. Add TargetDescriptor repository methods and SQLite persistence.
2. Implement the minimal local `application/target_catalog.py` registration and exact
   descriptor resolution workflow.
3. Replace ad hoc demo descriptor hashes with persisted Loan Agent TargetDescriptors.
4. Make Run creation reject missing or mismatched TargetDescriptor references.
5. Implement forward Run graph models and traversal in
   `application/lineage_queries.py`.
6. Add `GET /api/runs/{run_id}/lineage` and focused API tests.
7. Design and implement the A/B Test record, storage, and application workflow.
8. Expand lineage with A/B baseline/candidate relationships.
9. Add transactional Run-asset indexes and reverse repository queries.
10. Add Dataset, Case, Target, Skill, Evaluator, and A/B lineage endpoints.
11. Implement Web visualization and browser tests.
12. Reconcile architecture, progress, and operational documentation.

The first usable slice ends after step 6. It provides truthful Run lineage, including
Agent Skill versions resolved through persisted TargetDescriptors.

## 14. Coding And Security Rules

- RunManifest, TargetDescriptor, DatasetVersion, EvaluatorSpec, and A/B Run references are
  authoritative.
- Do not copy TargetDescriptor content into TargetSnapshot.
- Do not fetch mutable external metadata for historical lineage.
- Do not infer relationships from names.
- Do not persist rendered graph responses.
- Do not expose prompts, credentials, invocation configuration, Case inputs, Tool
  arguments, Trace payloads, or Result details in lineage nodes.
- Keep graph construction pure after records are loaded.
- Use typed node and relationship values; reject arbitrary free-form edge names.
- Keep SQL and indexing inside storage adapters.
- Do not add a graph library or graph database for deterministic traversal.
- Do not create a generic registry, factory, service wrapper, or compatibility facade.
- Keep code, APIs, docs, and tests in English; visible Web labels may be Chinese.

## 15. Verification

Backend tests must prove:

- TargetDescriptors persist idempotently by hash and remain immutable;
- multiple hashes for externally mutated content remain retrievable;
- Run creation rejects missing or mismatched descriptors;
- one Run expands to its exact Dataset, Cases, Target, descriptor Skills, and Evaluators;
- Agent and Skill Targets produce mutually exclusive Target edges;
- shared nodes and edge triples deduplicate;
- graph ordering is deterministic;
- Case or Skill content changes produce new content identities;
- A/B graphs contain baseline and candidate Runs and deduplicate shared assets;
- every reverse query returns all matching Runs within its limit;
- missing referenced records fail explicitly without leaking protected data;
- existing Dataset, Run, Result, comparison, CLI, and server tests remain green.

Web tests must verify desktop/mobile layout, shared-node handling, filters, node selection,
navigation, empty relationships, and failed API states.
