# Lineage Query And Visualization Implementation Plan

Last updated: 2026-09-08

## 1. Purpose

AgentGate must show the exact version relationships behind an Evaluation Run and answer
reverse questions such as which Runs used one Dataset version. The lineage view covers:

- Evaluation Runs;
- A/B Tests;
- Dataset versions and their Case content versions;
- Agent or Skill Target versions;
- Skill versions captured inside an Agent version;
- Evaluator versions.

Lineage is evidence derived from immutable execution records. It is not an independently
editable graph and it must not fetch mutable `latest` metadata while displaying history.

## 2. Relationship Model

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

The Dataset-to-Agent relationship is indirect:

```text
DatasetVersion <- used by - EvaluationRun - evaluates -> TargetVersion
```

An A/B Test references two ordinary Runs. It does not duplicate their Dataset, Target,
Skill, Case, or Evaluator snapshots.

### Relationships

| Source | Relationship | Target | Cardinality |
|---|---|---|---|
| A/B Test | `baseline_run` | Evaluation Run | exactly one |
| A/B Test | `candidate_run` | Evaluation Run | exactly one |
| Evaluation Run | `uses_dataset` | Dataset version | exactly one |
| Dataset version | `contains_case` | Case content version | one or more for a published Dataset |
| Evaluation Run | `evaluates_agent` | Agent version | zero or one |
| Evaluation Run | `evaluates_skill` | Skill version | zero or one |
| Agent version | `includes_skill` | Skill version | zero or more |
| Evaluation Run | `uses_evaluator` | Evaluator version | one or more |

Exactly one of `evaluates_agent` and `evaluates_skill` is present for a Run.

## 3. Ownership And Code Structure

```text
src/agentgate/
├── domain/
│   ├── target.py                 # immutable Agent and Skill snapshots
│   └── ab_test.py                # persisted A/B Test identity and Run references
├── application/
│   ├── run_management.py         # captures exact RunManifest inputs
│   ├── ab_testing.py             # creates and validates the two ordinary Runs
│   └── lineage_queries.py        # lineage read models and graph construction
├── storage/
│   ├── repository.py             # reverse-query and A/B persistence contracts
│   └── sqlite.py                 # SQLite implementation and query indexes
└── server/routes/
    └── lineage.py                # HTTP query endpoints

web/src/
└── pages/LineagePage.vue         # graph/tree visualization
```

Do not create a top-level `lineage/` package for this implementation. Graph construction
is a read-only application use case. Extract a dedicated package only when persisted graph
storage, arbitrary traversal, dependency-impact analysis, or reusable graph algorithms
become real requirements.

## 4. Source Of Truth

### RunManifest

`EvaluationRun.manifest` remains authoritative for Dataset, Case, Target, and Evaluator
relationships. The manifest is immutable after Run creation and already pins:

- one published `DatasetVersion` including ordered Cases;
- one exact `TargetSnapshot`;
- exact `EvaluatorSpec` versions and content hashes;
- metric and release-gate configuration;
- the complete manifest content hash.

### Skill snapshot gap

`TargetSnapshot` currently stores only the Target reference and descriptor hash. That is
insufficient to reconstruct the Skill versions used by a historical Agent Run.

Add the following field to `TargetSnapshot`:

```python
skills: tuple[SkillDescriptor, ...] = ()
```

The Target adapter/catalog captures these descriptors when the Run is created. Historical
lineage reads the snapshot only; it never asks the external Agent platform for current
Skill metadata. A Skill Target keeps this collection empty because the Target reference
itself identifies the evaluated Skill version.

### Case content versions

`Case` has a stable ID but no independent numeric revision. In lineage, a Case version is
identified by:

```text
Case ID + content SHA-256 + containing DatasetVersion
```

Do not invent a second Case revision counter solely for visualization.

### A/B Test record

The A/B capability must persist a focused record containing at least:

```text
id
baseline_run_id
candidate_run_id
created_at
```

Creation validates that both Runs use compatible Dataset content, primary Evaluators,
metric plans, and gate specifications. A/B execution and statistics remain owned by
`application/ab_testing.py` and `result/`; lineage only reads the relationship.

## 5. Application Read Models

`application/lineage_queries.py` defines transport-neutral read models. They are not
Domain entities and cannot be persisted as authoritative state.

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

Required invariants:

- node IDs are unique;
- edge triples are unique;
- every edge endpoint exists in `nodes`;
- `root_node_id` identifies an existing node;
- versioned executable assets contain exact versions;
- hashes are present whenever the source snapshot provides them.

Node metadata remains intentionally small. Full Dataset, Case, Target, or Evaluator data
is retrieved through its owning API rather than copied into the graph response.

## 6. Query API

Initial forward query:

```http
GET /api/runs/{run_id}/lineage
```

Expanded queries:

```http
GET /api/ab-tests/{ab_test_id}/lineage
GET /api/datasets/{dataset_id}/versions/{version}/lineage
GET /api/targets/{source_id}/{target_id}/versions/{version}/lineage
GET /api/evaluators/{evaluator_id}/versions/{version}/lineage
```

Behavior:

- unknown root resources return `404`;
- a valid resource with no related Runs returns a graph containing only the root node;
- malformed versions or limits return `422`;
- graph responses never expose Target invocation configuration, credentials, prompts,
  Case inputs, Tool arguments, or Trace payloads;
- endpoints are read-only and deterministic for unchanged stored records.

## 7. Graph Construction

Graph construction occurs at query time. Immutable records are written at Run/A/B
creation time; the rendered node-and-edge response is not stored.

Use three local collections:

```text
nodes_by_id: dict[str, LineageNode]
edges: set[tuple[source_id, target_id, relation]]
visited: set[str]
```

Core private operations in `application/lineage_queries.py`:

```text
_add_node()
_add_edge()
_expand_run()
_expand_dataset()
_expand_target()
_expand_ab_test()
```

Traversal is deterministic:

1. Load the requested root record.
2. Add the root node.
3. Expand only approved relationship types.
4. Deduplicate shared nodes by stable node ID.
5. Sort nodes and edges before constructing `LineageGraph`.

The work is ordinary visited-set traversal with `O(V + E)` complexity. Do not add
NetworkX or another graph library. PageRank, shortest path, cycle detection, and graph
databases are not required.

### Stable node identities

Node IDs are derived from immutable identities, not display names:

```text
run:{run_id}
ab_test:{ab_test_id}
dataset:{dataset_id}:{version}:{content_sha256}
case:{case_id}:{content_sha256}
target:{source_id}:{target_type}:{external_target_id}:{external_version_id}
skill:{source_id}:{external_skill_id}:{external_version_id}:{content_sha256}
evaluator:{evaluator_id}:{version}:{content_sha256}
```

Use structured values as hash inputs and established canonical hashing helpers. Do not
parse these IDs to recover business data.

## 8. Reverse Lookup Storage

Forward Run lineage needs only `repository.get_run(run_id)`. Reverse Dataset, Target, and
Evaluator queries must not inspect only the latest 50 Runs or load all Runs indefinitely.

Add explicit repository operations:

```python
list_runs_by_dataset_version(dataset_id, version, limit)
list_runs_by_target_version(source_id, target_id, version, limit)
list_runs_by_evaluator_version(evaluator_id, version, limit)
list_ab_tests_by_run_ids(run_ids)
```

SQLite may maintain derived, indexed Run-asset reference rows when a pending Run is first
persisted. These rows accelerate reverse lookup but are not a second source of truth. They
must be written in the same transaction as the immutable Run and must be reproducible from
its RunManifest.

Do not query arbitrary JSON paths from application code. SQLite-specific indexing and SQL
remain inside `storage/sqlite.py`.

## 9. Web Visualization

`LineagePage.vue` renders the API graph without introducing lineage business rules.

Required views:

- Run-centered dependency tree;
- A/B baseline and candidate branches;
- shared Dataset and Evaluator nodes shown once;
- node details with ID, type, version, and hash;
- navigation from a node to its owning Dataset, Run, Result, Evaluator, or Target page.

Use a proven graph/layout library already approved for the Web stack if free-form graph
layout becomes necessary. A deterministic tree/DAG layout is sufficient initially. The
frontend must not infer missing relationships from names or current external metadata.

## 10. Source Assessment

### `goal/p1-demo`

- `lineage/` and `experiment/` contain only one-line placeholders.
- There is no graph model, traversal, persistence, or API implementation to reuse.
- Preserve only the concepts of reproducible snapshots and experiment relationships.

### `team/integration-p1-new`

- The single-Case rerun records parent/root Run IDs and demonstrates why explicit Run
  relationships matter.
- Its comparison and rerun behavior is coupled to the rejected broad Control Plane,
  mutable dictionaries, and obsolete RunSnapshot contracts.
- Reuse the parent-reference idea only when a current regression workflow is designed;
  do not copy its lineage code.

### Current refactor

Reuse directly:

- immutable `RunManifest`, `DatasetVersion`, `Case`, `TargetSnapshot`, and
  `EvaluatorSpec`;
- repository boundaries and SQLite transaction handling;
- current FastAPI dependency and error conventions;
- `result/comparison.py` for compatible Run comparison.

Write from scratch:

- Skill snapshot capture in the current Target contract;
- A/B Test persistence and application orchestration;
- lineage read models, deterministic graph construction, reverse query indexes, APIs,
  and Web visualization.

Reuse means adapting validated behavior to current contracts, not copying old files.

## 11. Implementation Sequence And Approval Checkpoints

Each file follows the project approval sequence: filename, responsibility, class/function
design, source assessment, then implementation and tests.

1. Update `domain/target.py` to capture immutable Skill descriptors in TargetSnapshot.
2. Add focused TargetSnapshot lineage tests and update demo Target construction.
3. Implement forward Run graph read models and construction in
   `application/lineage_queries.py`.
4. Add `GET /api/runs/{run_id}/lineage` and API tests.
5. Design and implement the focused A/B Test domain/application/storage capability.
6. Expand lineage construction with A/B baseline/candidate relationships.
7. Add indexed reverse Run-asset lookups to repository and SQLite adapters.
8. Add Dataset, Target, Evaluator, and A/B root endpoints.
9. Implement `LineagePage.vue` and desktop/mobile browser tests.
10. Reconcile project progress and architecture documentation.

The first usable slice ends after step 4. It shows complete Run dependencies, including
captured Agent Skill versions, without waiting for the A/B module.

## 12. Coding Rules

- RunManifest and persisted A/B references are authoritative; graph output is derived.
- Never fetch mutable external metadata to reconstruct historical lineage.
- Never infer relationships from display names.
- Do not duplicate Dataset, Target, Skill, or Evaluator content in an A/B record.
- Do not persist rendered graph responses.
- Do not expose prompts, credentials, invocation configuration, Case inputs, or Trace data.
- Keep graph construction pure after records are loaded.
- Use explicit relationship types; do not accept arbitrary free-form edge names.
- Keep storage-specific SQL out of application modules.
- Do not add a graph library or graph database for deterministic POC traversal.
- Do not create compatibility aliases for deleted scaffolds.
- Keep code, API fields, documentation, and tests in English; Web labels may be Chinese.

## 13. Verification

Backend tests must prove:

- one Run expands to the exact Dataset, Cases, Target, Skills, and Evaluators pinned by
  its manifest;
- Agent and Skill Targets produce the correct mutually exclusive Target edge;
- shared nodes and edges are deduplicated;
- graph ordering is deterministic;
- Case content changes produce a different Case version identity;
- unknown roots return `404`;
- A/B graphs include two Run branches and deduplicate compatible shared assets;
- reverse queries return all matching Runs within the requested limit, not merely the
  latest global Run page;
- graph responses omit protected execution data;
- existing Run, Dataset, Result, and comparison tests remain green.

Web tests must verify readable layouts at desktop and mobile sizes, shared-node handling,
node selection, navigation, empty relationships, and failed API states.
