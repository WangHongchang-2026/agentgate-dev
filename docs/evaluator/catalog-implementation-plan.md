# Evaluator Catalog Implementation Plan

## Goal

Implement the POC Evaluator Catalog as a persistent product capability while preserving
the evaluator runtime completed on `refactor-1`.

The catalog must let a user create a configured Evaluator, edit one draft, publish
immutable versions, enable or disable the Evaluator for new Runs, retrieve exact versions,
and remove an Evaluator that has never been published. Built-in Evaluators remain visible
and selectable but read-only.

```text
supported implementation
  -> user Evaluator identity
  -> editable draft
  -> publish immutable EvaluatorSpec
  -> select latest enabled publication for a new Run
  -> embed exact EvaluatorSpec in RunManifest
  -> execute through the existing evaluator runtime
```

“User-created Evaluator” means a user-authored configuration of an implementation that
AgentGate already supports. This increment does not accept executable Python, uploaded
plugins, expressions, or arbitrary remote code.

## Scope

This increment includes:

- persistent user Evaluator identities, drafts, and published versions in SQLite;
- create, read, update, constrained delete, draft, publish, and enable/disable workflows;
- exact-version reads and latest-version selection;
- a unified read model containing built-in and user Evaluators;
- integration with Run creation and historical Run execution;
- REST APIs and focused backend tests.

This increment excludes:

- tenant isolation, users, roles, and permissions;
- provider or credential administration;
- Web implementation;
- custom executable evaluator code;
- import/export and marketplace behavior;
- deprecating published versions;
- compatibility aliases for the old read-only response;
- PostgreSQL, distributed catalog invalidation, and catalog caching.

## Current State And Gap

`application/evaluator_management.py` currently constructs an in-memory runtime catalog.
It validates built-in specifications against concrete implementations, selects an
Evaluator set for a Run, validates the selected plan, and executes it. The server exposes
those specifications through read-only `GET /api/evaluators` in
`server/routes/catalogs.py`.

The current implementation has no user-owned identity, draft lifecycle, persistent
version store, enable state, exact-version query, or mutation API. Its built-in tuple is a
valid runtime composition input, not a complete Evaluator Catalog product capability.

## Baseline Assessment

### `goal/p1-demo`

Reuse:

- `EvaluatorSpec` as the immutable definition embedded in a Run;
- exact implementation and operator version checks;
- preflight failure rather than delayed runtime failure.

Do not reuse:

- import-time global evaluator registration;
- decorator-based discovery;
- the deferred Judge resolver;
- mutable process-global dictionaries as product persistence.

The P1 implementation contains no persistent evaluator lifecycle or CRUD API. Its useful
ideas have already been adapted into explicit composition on `refactor-1`.

### `integration/p1-new`

Adapt:

- the UI-facing distinction between `builtin` and `user` Evaluators;
- built-ins being read-only;
- list rows showing kind, dimension, metric, severity, version, and source.

Do not copy:

- its `evaluator_type` field, because the current clean-break contract uses
  `implementation_id` and `implementation_version`;
- its fallback that silently treats a missing source as built-in;
- its disabled “future” actions as evidence of implemented backend behavior.

That branch has a read-only Web client and placeholder page, not a backend catalog.

### Settled `refactor-1`

This plan was revalidated after result comparison and Run lineage were integrated at
`78f9dfa`. The integrated baseline passes 551 tests. Catalog implementation starts from
that commit rather than the earlier evaluator-only head.

Reuse unchanged where possible:

- `domain/evaluator.py` kinds, severity, composition, credential rejection, and
  content-addressed `EvaluatorSpec`;
- concrete Rule and Judge implementations;
- `evaluator/executor.py` execution and failure isolation;
- evaluator plan validation and exact Run snapshots;
- the configured POC Judge provider boundary;
- the SQLite JSON-document persistence style;
- repository-backed `TargetCatalog` composition as a nearby application-boundary
  pattern;
- `list_runs_by_evaluator_version(...)` and `LineageQueries`, which already provide
  historical Run lookup for an exact published Evaluator version.

Adapt:

- `EvaluatorManagement` from an in-memory-only list to application-owned catalog
  workflows plus runtime resolution;
- server dependency construction so API and workers receive the same supported
  implementations while only API workflows mutate the catalog;
- Run selection so explicit user Evaluator IDs resolve to their latest enabled published
  versions;
- CLI, Celery, test-fixture, and server construction so every `EvaluatorManagement`
  instance receives the repository that owns its catalog.

Do not introduce a generic catalog base class from the similarity with `TargetCatalog`.
Target descriptors are immutable content-addressed registrations, while Evaluators have
identity, draft, publication, and enable-state lifecycles.

Write from scratch:

- Evaluator identity and draft domain contracts;
- persistent catalog repository operations and SQLite tables;
- mutation and version APIs;
- catalog-specific lifecycle tests.

## Terms And Ownership

### Evaluator

A stable catalog identity with user-editable display metadata and availability state. An
Evaluator owns zero or more immutable published versions and at most one draft.

### Evaluator draft

Mutable configuration that is not executable, selectable by a Run, or addressable as a
published version. A draft may be submitted without a base version or cloned from an
existing publication, but its submitted configuration is always structurally complete.
Cross-catalog and deployment checks occur at publication.

### EvaluatorSpec

The existing immutable, content-addressed executable snapshot. Publishing a draft creates
an `EvaluatorSpec`; a Run embeds that exact object in its manifest.

### Supported implementation

A concrete Rule, Judge, or Hybrid execution implementation composed by AgentGate. Catalog
records may configure these implementations but may not create new executable code.

### Built-in Evaluator

A source-controlled `EvaluatorSpec` supplied by AgentGate. Built-ins are always read-only,
are not copied into SQLite, and remain part of the default Run evaluator set.

### User Evaluator

An Evaluator identity stored in SQLite. It must have a published version and be enabled
before it can be selected for a new Run.

Ownership boundaries:

```text
domain/evaluator.py
  Evaluator identity, source, draft data, and local lifecycle invariants

evaluator/
  concrete implementations, execution, and evaluator-specific validation

application/evaluator_management.py
  catalog workflows, publication, selection, and preflight coordination

storage/
  atomic persistence and version allocation

server/routes/evaluators.py
  HTTP request/response translation only

application/run_management.py
  asks EvaluatorManagement to resolve exact selectable specifications

RunManifest
  preserves exact published specifications for historical execution
```

## Lifecycle And Invariants

### Stable identity

Add `Evaluator` with:

- `id`: stable non-blank identifier generated by the application;
- `name`: non-blank editable display name;
- `description`: editable display text;
- `source`: closed `builtin | user` value;
- `enabled`: availability for new explicit Run selection;
- `created_at` and `updated_at`: normalized UTC timestamps.

Only `user` identities are persisted. Built-in summaries are projected from their specs.
The `source` value is returned by the application and API; callers never choose `builtin`
when creating an Evaluator. A new user Evaluator starts disabled because it has no
publication that a Run can select.

### Draft

Add `EvaluatorDraft` with:

- an immutable draft ID and owning `evaluator_id`;
- optional `based_on_version` using the existing string version contract;
- kind, dimension, metric, severity, implementation ID and version;
- open-ended validated config;
- exact Hybrid child references and combination policy;
- created and updated timestamps.

There is at most one active draft per user Evaluator. Draft data observes the same kind,
composition, non-blank, and plaintext-credential invariants as `EvaluatorSpec`, but it has
no version or content hash and cannot be executed.

### Publishing

Publishing is one SQLite transaction:

1. Load the current draft and owning enabled or disabled user identity.
2. Validate its supported implementation and complete configuration.
3. Resolve and validate exact Hybrid child publications, if any.
4. Allocate the next integer version under the Evaluator identity.
5. Convert that number to the existing `EvaluatorSpec.version` string.
6. Construct the immutable `EvaluatorSpec`, including its content hash.
7. Insert the publication and remove the exact draft.

The first publication is `"1"`; subsequent publications increment by one. No version is
reused. Publication must fail atomically if the draft changed or another publisher won a
race.

### Editing

An update replaces the complete editable draft body. Full replacement avoids ambiguous
merge behavior in open-ended JSON config. Identity name and description are updated
separately. Creating a new draft may use the latest publication or a requested exact
publication as its base.

Published `EvaluatorSpec` objects are immutable. Editing always targets a draft and never
rewrites a published row.

### Enable and disable

Only user Evaluators can change availability. Enabling requires at least one published
version. A disabled Evaluator:

- is omitted from the default catalog list unless `include_disabled=true`;
- cannot be selected for a new Run;
- remains retrievable with all publications and draft data;
- remains executable from a historical `RunManifest`.

Built-ins are always enabled in this POC and reject mutation attempts.

### Delete

Hard delete is permitted only for a user Evaluator with no publications. The delete
transaction removes its draft and stable identity. Once any version has been published,
the identity and versions must be retained; disable is the supported removal action.

This rule protects historical references and avoids adding tombstone or cascade semantics
that the POC does not need.

## Domain Design

Modify `domain/evaluator.py` to add:

- `EvaluatorSource`;
- `Evaluator`;
- `EvaluatorDraft`.

Keep `EvaluatorSpec` as the published execution contract. Do not add lifecycle flags,
draft state, timestamps, or persistence concerns to it.

Shared validation for draft and published configuration should be small plain functions
in the same module. Do not introduce an inheritance hierarchy or a passive “definition”
wrapper solely to share fields.

Publication conversion belongs in a new `evaluator/versioning.py` as pure functions:

- `create_evaluator_draft(...)`;
- `replace_evaluator_draft(...)`;
- `publish_evaluator_draft(...)`.

These functions receive timestamps and IDs from callers, return new immutable domain
objects, and perform no storage or clock access.

## Persistence Design

Extend the existing `AgentGateRepository` boundary and `SQLiteRepository`; do not add a
second repository abstraction for the same SQLite transaction owner.

Add three tables:

```text
evaluators
  id PK, enabled, created_at, updated_at, payload

evaluator_drafts
  id PK, evaluator_id UNIQUE FK, updated_at, payload

evaluator_versions
  evaluator_id FK, version INTEGER, content_sha256, payload,
  PRIMARY KEY (evaluator_id, version)
```

The payload is authoritative domain JSON. Indexed columns enforce identity, single-draft,
ordering, and uniqueness constraints. Version rows store the numeric form for correct
ordering and serialize the public version as a string inside `EvaluatorSpec`.

Repository operations:

- save, get, list, and delete an unpublished user Evaluator;
- save, get, and delete the exact active draft;
- list and retrieve published specifications;
- retrieve the latest published specification;
- atomically replace a draft with its next publication.

Repository writes reject stale timestamps, identity changes, built-in source values,
published-content replacement, draft-owner mismatch, and content-hash mismatch.

No migration framework is added. Existing databases are upgraded idempotently by the
current `CREATE TABLE IF NOT EXISTS` initialization approach.

## Application Design

`EvaluatorManagement` remains the application entry point. It receives:

- `AgentGateRepository`;
- immutable built-in specifications;
- the explicit implementation mapping.

`build_default_evaluator_management(repository, ...)` requires the repository explicitly.
Remove the repository-free `DEFAULT_EVALUATOR_MANAGEMENT` process global. Server, CLI,
Celery, and tests construct management against their own repository so catalog selection
cannot accidentally read a different database from Run persistence.

It owns these workflows:

- list and get unified catalog entries;
- create and update a user Evaluator identity;
- create, read, replace, and discard its draft;
- publish a draft;
- list and get exact published versions;
- enable, disable, and conditionally delete a user Evaluator;
- resolve specifications for a new Run;
- validate a Run plan and execute a Case through the existing executor.

The implementation mapping remains deployment composition, not catalog data. Publishing
and Run selection both reject unknown implementation IDs, version mismatch, kind mismatch,
unavailable Judge providers, invalid JSON Schema configuration, and invalid Hybrid
references before a Run is persisted.

Selection semantics:

- omitted `evaluator_ids` preserves the current default built-in set;
- explicit IDs may mix enabled built-ins and enabled published user Evaluators;
- a user ID resolves to its latest publication at Run-creation time;
- duplicate, unknown, disabled, or unpublished IDs fail preflight;
- dependencies required by a Hybrid are resolved as exact published child versions;
- the resulting tuple is embedded unchanged in `RunManifest`.

Adding a user Evaluator must therefore never silently add it to every future Run.

Historical worker execution uses specifications already stored in `RunManifest`. It must
not re-query enable state or substitute a newer catalog version. It still requires the
referenced concrete implementation version to exist in the worker deployment.

The integrated lineage boundary already reads exact Evaluator versions from persisted Run
manifests. Catalog work must preserve `list_runs_by_evaluator_version(...)`; it does not
add another Run-to-Evaluator index, query service, or lineage representation.

## REST API

Move `GET /api/evaluators` from `server/routes/catalogs.py` into a dedicated
`server/routes/evaluators.py`. This is a clean-break response contract; do not preserve a
second route implementation or legacy field aliases.

```text
GET    /api/evaluators?include_disabled=false
POST   /api/evaluators
GET    /api/evaluators/{evaluator_id}
PATCH  /api/evaluators/{evaluator_id}
DELETE /api/evaluators/{evaluator_id}

GET    /api/evaluators/{evaluator_id}/versions
GET    /api/evaluators/{evaluator_id}/versions/{version}

GET    /api/evaluators/{evaluator_id}/drafts/current
POST   /api/evaluators/{evaluator_id}/drafts
PUT    /api/evaluators/{evaluator_id}/drafts/current
DELETE /api/evaluators/{evaluator_id}/drafts/current
POST   /api/evaluators/{evaluator_id}/drafts/publish
```

`POST /api/evaluators` creates a user identity and its first draft atomically. The caller
supplies display metadata and the complete draft body but not IDs, source, timestamps,
version, or content hash.

`PATCH /api/evaluators/{id}` accepts only `name`, `description`, and `enabled`. Empty
patches and attempts to mutate a built-in return validation errors.

List entries include identity fields, source, enabled state, latest published version,
and whether a draft exists. Detail includes the identity, latest publication, and current
draft. Version endpoints return exact `EvaluatorSpec` objects. Read and exact-version
endpoints also work for projected built-ins; their mutation and draft endpoints reject the
operation.

HTTP behavior:

- `201` for identity/draft creation;
- `200` for reads, updates, and publication;
- `204` for draft discard and allowed hard delete;
- `404` for unknown identities, drafts, or versions;
- `409` for lifecycle conflicts such as duplicate draft, stale publication, enabling an
  unpublished Evaluator, or deleting a published Evaluator;
- `422` for invalid domain configuration or unsupported implementations.

Routes translate transport models and errors only. They do not allocate versions,
validate implementations, query SQLite directly, or compose runtime evaluators.

## Proposed Code-Change Tree

Status labels are proposals to be confirmed again during file-level implementation.

```text
agentgate-goal/
├── src/agentgate/
│   ├── domain/
│   │   ├── evaluator.py                         [MOD] Identity, source, draft invariants
│   │   └── __init__.py                          [MOD] Confirmed public exports
│   ├── evaluator/
│   │   └── versioning.py                        [ADD] Pure draft/publication transformations
│   ├── application/
│   │   ├── __init__.py                           [MOD] Confirmed application export
│   │   └── evaluator_management.py              [MOD] Catalog lifecycle and Run resolution
│   ├── storage/
│   │   ├── repository.py                        [MOD] Catalog persistence operations
│   │   └── sqlite.py                            [MOD] Tables and atomic transactions
│   ├── cli/
│   │   └── main.py                               [MOD] Repository-bound evaluator composition
│   ├── integrations/job_dispatchers/
│   │   └── celery.py                             [MOD] Worker composition against Run repository
│   └── server/
│       ├── app.py                               [MOD] Register evaluator router
│       ├── dependencies.py                      [MOD] Repository-backed management lifecycle
│       └── routes/
│           ├── catalogs.py                      [MOD] Retain target-version catalog only
│           ├── evaluators.py                    [ADD] Evaluator REST boundary
│           └── __init__.py                      [MOD] Route exports
├── tests/
│   ├── test_evaluator_models.py                 [MOD] Identity and draft invariants
│   ├── test_evaluator_versioning.py             [ADD] Pure lifecycle transformations
│   ├── test_evaluator_management.py             [MOD] Workflows and selection
│   ├── test_evaluator_repository.py             [ADD] Persistence and atomic publication
│   ├── test_evaluator_api.py                    [ADD] REST contracts and errors
│   ├── test_run_management.py                   [MOD] Latest-version snapshot selection
│   ├── test_server_app.py                       [MOD] Dependency construction behavior
│   ├── test_server_dependencies.py              [MOD] Repository ownership
│   ├── test_server_catalog_routes.py            [MOD] Read route moves cleanly
│   ├── test_celery_dispatcher.py                [MOD] Worker repository composition
│   ├── test_cli_run_commands.py                 [MOD] CLI repository composition
│   ├── test_cli_result_commands.py              [MOD] Shared Run setup
│   ├── test_result_reader.py                    [MOD] Shared Run setup
│   ├── test_manifest_immutability.py            [MOD] Repository-bound management
│   ├── test_lineage_queries.py                  [MOD] Preserve exact evaluator lineage
│   ├── test_storage_lineage.py                  [MOD] Preserve integrated storage behavior
│   └── conftest.py                              [MOD] Repository-bound evaluator fixture
└── docs/
    ├── evaluator/
    │   ├── README.md                            [MOD] Describe persistent catalog
    │   └── catalog-implementation-plan.md       [ADD] This plan
    ├── architecture.md                          [MOD] Confirm catalog lifecycle ownership
    └── project-progress.md                      [MOD] Update after verified delivery
```

No existing production file is deleted. The read route moves, but `catalogs.py` remains
the owner of target-version demo discovery. The existing result-comparison and lineage
files are preserved without catalog responsibilities.

## Delivery Checkpoints

The project approval workflow still applies. For each file below, confirm responsibility
and detailed design before implementation.

### 1. Domain contracts

1. `domain/evaluator.py`
2. focused model tests in `test_evaluator_models.py`
3. `domain/__init__.py` after the public contracts stabilize

Acceptance: invalid identities, timestamps, draft composition, credential-like config,
and source values fail at construction; valid objects serialize deterministically.

### 2. Pure versioning

1. `evaluator/versioning.py`
2. `test_evaluator_versioning.py`

Acceptance: draft creation, replacement, cloning from a publication, and publication are
pure, immutable, sequential, and content-addressed.

### 3. Storage

1. `storage/repository.py`
2. `storage/sqlite.py`
3. `test_evaluator_repository.py`

Acceptance: persistence round-trips, uniqueness, stale writes, atomic publication,
immutable versions, and constrained deletion work on fresh and existing databases.

### 4. Application workflows

1. `application/evaluator_management.py`
2. application export and repository-bound construction sites
3. `test_evaluator_management.py`
4. `test_run_management.py`
5. affected CLI, Celery, lineage, result-reader, and fixture tests

Acceptance: built-in/user merge, draft lifecycle, publication, availability, latest
selection, explicit selection, and historical execution follow this plan.

### 5. HTTP boundary

1. `server/routes/evaluators.py`
2. `server/routes/catalogs.py`
3. route exports, dependencies, and application assembly
4. `test_evaluator_api.py` and affected API regression tests

Acceptance: all endpoints, clean-break payloads, status codes, and lifecycle conflicts are
covered through the public FastAPI application.

### 6. Documentation and regression

1. update `docs/evaluator/README.md` and `docs/architecture.md`;
2. run focused evaluator, repository, Run, and API tests;
3. run the complete Python regression suite;
4. update only the Evaluator Catalog entries in `docs/project-progress.md` after all
   required behavior passes; preserve unrelated integrated feature statuses.

## Acceptance Scenarios

At minimum, automated tests cover:

1. built-ins appear as enabled, read-only catalog entries;
2. creating a user Evaluator also creates exactly one draft;
3. a user cannot claim built-in source or choose server-owned fields;
4. a second active draft is rejected;
5. a draft can be based on an exact publication;
6. replacing a draft cannot change its identity;
7. plaintext credentials are rejected in draft config;
8. unknown implementation IDs or versions cannot publish;
9. implementation kind mismatch cannot publish;
10. invalid Judge configuration cannot publish;
11. invalid Hybrid child references cannot publish;
12. first publication is version `"1"` with a valid content hash;
13. the next publication is version `"2"` and version `"1"` remains unchanged;
14. concurrent or stale publication cannot duplicate a version;
15. enabling an unpublished Evaluator is rejected;
16. disabling prevents new Run selection;
17. disabling does not prevent exact-version reads;
18. a Run created before disable still executes from its manifest;
19. omitted evaluator IDs retain the default built-in set;
20. explicit mixed built-in/user selection embeds exact specifications;
21. deleting an unpublished Evaluator removes its draft;
22. deleting a published Evaluator is rejected;
23. exact version endpoints distinguish unknown identity from unknown version;
24. existing databases initialize catalog tables without losing prior data;
25. evaluator-version lineage still returns Runs containing that exact publication;
26. current Rule-only and configured Judge regressions remain green;
27. result-comparison and Run-lineage regressions remain green.

End-to-end acceptance:

```text
POST user Evaluator with draft
  -> publish version "1"
  -> enable
  -> create Run selecting its ID
  -> RunManifest contains exact version and content hash
  -> execute using the supported implementation
  -> edit a new draft and publish version "2"
  -> old Run still reproduces version "1"
  -> new Run resolves version "2"
```

## Design Constraints

1. Do not persist concrete Python evaluator instances.
2. Do not recover implementations through import strings or dynamic imports.
3. Do not put credentials in drafts, publications, API responses, or Run manifests.
4. Do not mutate or delete a published `EvaluatorSpec`.
5. Do not make catalog enable state part of historical Run execution.
6. Do not silently select every user Evaluator when a Run omits evaluator IDs.
7. Do not copy built-ins into SQLite or create two authorities for their definitions.
8. Do not make routes responsible for lifecycle or version allocation.
9. Do not add a factory, registry, plugin framework, event bus, or generic service layer.
10. Do not add compatibility response fields from `integration/p1-new`.
11. Do not couple domain objects to FastAPI, SQLite, provider clients, or UI concerns.
12. Do not start the Web implementation in this backend increment.

## Implementation Result

The persistent catalog described by this plan is implemented on
`feature/evaluator-catalog` against integrated baseline `78f9dfa`.

Delivered behavior includes:

- unified built-in and user `Evaluator` identities with non-null timestamps;
- one persistent editable draft and immutable sequential publications;
- atomic SQLite identity-plus-draft creation and draft publication;
- exact version reads, enable and disable, and constrained hard deletion;
- publication validation for supported Rule and Judge implementations;
- latest enabled user-version selection for new Runs;
- exact `RunManifest` snapshots that remain executable after disable or later publication;
- repository-bound server, Celery, CLI, and test composition;
- removal of the repository-free `DEFAULT_EVALUATOR_MANAGEMENT` global;
- `default_specs` as the explicit built-in selection set;
- twelve clean-break REST endpoints under `/api/evaluators`;
- typed `404`, `409`, and `422` HTTP failure mapping, including stale publication
  conflicts.

The implementation retains the POC boundaries in this plan: supported configurations do
not create executable code, model providers remain process-configured, built-ins are not
stored in SQLite, and Web implementation remains separate.

Final complete-suite verification is recorded in `docs/project-progress.md` after the
documentation changes are included.

## Required Verification

Focused verification must include domain, versioning, repository, application, Run, and
API tests after their respective checkpoints. Before declaring the feature complete, run:

```text
pytest -q
```

The feature is complete only when the end-to-end acceptance path works, the complete
regression suite passes, the architecture and evaluator documentation match the delivered
contracts, and `docs/project-progress.md` records the result.
