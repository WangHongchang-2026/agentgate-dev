# Dataset Implementation Plan

Status: backend implementation complete; generation and public benchmarks remain
separate future capabilities tracked in `docs/project-progress.md`

Authority:

1. `docs/architecture.md`
2. `docs/architecture-review-ledger.md`
3. `docs/refactor-implementation-plan.md`
4. This plan

The implementation starts from `refactor-1`. Team branches are review inputs only and
are not merged wholesale.

## 1. Goal

Refactor the working P1 Dataset workflow into clear reusable and application layers:

```text
Web / CLI / API
       |
       v
application/dataset_management.py    user workflow
       |
       +----> dataset/                transformations and formats
       |
       v
storage/repository.py                persistence contract
```

The completed capability supports:

- Dataset catalog create, read, update, archive, and copy;
- one editable draft per Dataset;
- Case add, update, copy, remove, and reorder;
- immutable numbered publication;
- single-turn and multi-turn Cases;
- canonical JSON import/export;
- simple one-sheet Excel `.xlsx` import/export for business-unit data exchange;
- exact published DatasetVersion resolution for Evaluation Runs.

## 2. Terms

- **Dataset**: stable catalog identity and editable display metadata.
- **DatasetVersion**: immutable content snapshot containing ordered Cases.
- **Draft**: editable candidate for the next version; never runnable.
- **Published version**: immutable numbered DatasetVersion selectable by a Run.
- **Case**: one single-turn or multi-turn evaluation scenario.
- **Format adapter**: converts external bytes/rows to plain structured data and back.
- **Loader**: converts format output into validated domain objects.

## 3. Final File Map

```text
dataset/
├── __init__.py
├── loader.py
├── export.py
├── versioning.py
└── formats/
    ├── __init__.py
    ├── json.py
    └── xlsx.py

application/
├── __init__.py
└── dataset_management.py
```

Deferred until a real caller exists:

```text
dataset/sampling.py
dataset/generation/
```

Do not create empty placeholders for deferred capabilities.

## 4. File Changes

| Current | Action | Destination |
| --- | --- | --- |
| `case/import_export.py` | Split | `dataset/loader.py`, `dataset/export.py`, `dataset/formats/json.py` |
| none | Add | `dataset/formats/xlsx.py` |
| `case/service.py` | Split | `dataset/versioning.py`, `application/dataset_management.py` |
| `case/validation.py` | Remove after ownership migration | Domain and application layers |
| empty `case/customer/` | Remove | Recreate only for a real format |
| empty `case/public_benchmarks/` | Remove | Add only implemented benchmark integrations |
| `case/` | Remove | Replaced by `dataset/` |

No compatibility alias from `agentgate.case` is retained.

## 5. Module Contracts

### `dataset/versioning.py`

Pure immutable transformations:

- create a draft from an optional published base;
- add or replace a Case while preserving identity;
- remove a Case;
- copy a Case with a new ID;
- reorder Cases only when every Case appears once;
- build a published DatasetVersion from a draft, explicit version number, publication
  ID, and timestamp;

It performs no repository, SQL, HTTP, or global-state access. IDs and timestamps are
passed in when deterministic behavior matters. Publication rejects a non-draft source
and an empty Dataset.

### `dataset/formats/json.py`

Own the canonical external envelope and JSON byte/string conversion:

```text
format = agentgate.dataset
format_version = 1
dataset = Dataset payload
version = DatasetVersion payload
```

It checks envelope syntax and format version. It does not persist or publish.

### `dataset/formats/xlsx.py`

Implement `.xlsx` exchange with `openpyxl` using one `Cases` sheet. One row represents
one conversation Turn; repeated `case_id` values form a multi-turn Case and `turn_order`
controls conversation order. The columns are:

```text
case_id, case_name, category, difficulty, tags_json, case_notes,
initial_state_json, turn_id, turn_order, input_json, expectations_json, turn_notes
```

Only `case_id`, `case_name`, and `input_json` are required. JSON-valued cells use
canonical JSON. Import errors identify sheet, row, and column. The adapter rejects
formulas, unsafe active workbook content, malformed archives, excessive expansion, and
lossy JSON values. Dataset catalog identity is supplied by the application workflow and
is not encoded in this simple sheet.

Excel is a compatibility and bulk-exchange channel, not the primary Dataset editor.
Users perform full Case, Turn, Expectation, and draft editing through the Web UI.

### `dataset/loader.py`

- select an implemented adapter from an explicit format argument;
- parse external input;
- construct Dataset, DatasetVersion, Case, CaseTurn, and Expectation domain objects;
- reject unsupported versions and expectation kinds;
- return validation errors with stable locations.

It does not save data or decide how identity conflicts are resolved.

### `dataset/export.py`

- verify Dataset and DatasetVersion identities match;
- build the canonical export representation;
- delegate JSON or XLSX encoding;
- return bytes, media type, and suggested filename.

It does not query storage or construct HTTP responses.

### `application/dataset_management.py`

Move the current `DatasetService` workflows here. Review the class name during the file
checkpoint rather than retaining it automatically.

Responsibilities:

- coordinate catalog CRUD, archive, and copy workflows;
- resolve not-found and conflict conditions;
- call pure versioning transformations;
- determine the next published version number;
- require a nonempty valid draft before publication;
- call the repository's atomic draft-replacement operation;
- coordinate import identity policy and persistence;
- coordinate export retrieval and encoding;
- resolve an exact published DatasetVersion for Run manifest creation.

It contains no SQL, XLSX row parsing, Agent execution, or Result calculation.

## 6. Validation Ownership

```text
External syntax / workbook shape       dataset/formats/
External-to-domain conversion          dataset/loader.py
Field and aggregate invariants         domain/case.py, domain/dataset.py
Draft workflow and publication rules   application/dataset_management.py
Evaluator availability/preflight       later Run composition
SQL constraints and atomicity           storage/sqlite.py
```

Remove `case/validation.py` after migrating valid responsibilities:

- duplicate Case, Turn, and Expectation IDs belong in domain models;
- blank typed fields belong in domain models;
- nonempty publication belongs in the application workflow;
- evaluator support for `MatchesJsonSchema` belongs in Run preflight, not Dataset
  validity.

## 7. Implementation Sequence

Follow the project checkpoint rule: approve one file's name/responsibility, then review
classes/functions, implement it, and run focused tests before moving on.

1. [complete] Confirm the final Dataset file map and baseline behavior.
2. [complete] Implement `dataset/versioning.py` pure transformations.
3. [complete] Implement `dataset/formats/json.py` and preserve canonical JSON round trips.
4. [complete] Implement `dataset/loader.py` and `dataset/export.py`.
5. [complete] Add one-sheet `.xlsx` import/export in `dataset/formats/xlsx.py`.
6. [complete] Integrate XLSX parsing into `dataset/loader.py` and XLSX encoding into
   `dataset/export.py`.
7. [complete] Implement `application/dataset_management.py` and migrate all callers.
8. [complete] Integrate the approved atomic Dataset creation and draft-publication
   operations in `storage/repository.py`.
9. [complete] Remove `case/`, duplicate validation, stale imports, and empty scaffolds.
10. [complete] Update existing API/CLI imports only as required; transports and Web were
    not redesigned.
11. [complete] Run focused and complete backend regression suites.

Each checkpoint should produce a small reviewable commit when practical.

## 8. Implementation Decisions

Record the source assessment here before implementing each file. The architecture ledger
tracks only overall progress.

### `dataset/export.py`

Status: implemented; 185 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Reuse the Dataset/DatasetVersion identity check and canonical envelope fields. |
| `goal/p1-demo` | Reject the old `DatasetExport` Pydantic wrapper and combined import/export module. |
| `integration/p1-new` | Adapt its safe attachment filename normalization into a format-independent suggested filename. |
| `integration/p1-new` | Reject HTTP `Content-Disposition` handling here; it belongs in `server/`. |
| From scratch | Add the `ExportedDataset` bytes/media-type/filename output contract and explicit format dispatch. |
| Deferred | Integrate the XLSX adapter through `dataset/loader.py` and `dataset/export.py` in separate approved checkpoints. |

### `dataset/formats/xlsx.py`

Status: implemented; 195 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | No XLSX behavior or code existed to reuse. |
| `integration/p1-new` | Preserve archive limits, active-content rejection, formula protection, located errors, Case grouping, and Turn ordering. |
| `integration/p1-new` | Rewrite the implementation around one responsibility, current domain fields, and plain Case payloads. |
| `integration/p1-new` | Reject obsolete convenience fields, Dataset persistence, HTTP handling, and its three-sheet workbook. |
| From scratch | Add the current 12-column schema, current Expectation payload handling, strict JSON cells, and format-only `parse`/`dump` functions. |

### `dataset/loader.py` XLSX integration

Status: implemented; 197 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | No XLSX loading behavior or code existed to reuse. |
| `integration/p1-new` | Preserve the behavior of parsing Cases before constructing a Dataset draft. |
| `integration/p1-new` | Reuse no code directly; its parsing, domain construction, workflow, and persistence were coupled. |
| `integration/p1-new` | Reject Dataset creation, repository writes, and publication rules from the loader. |
| From scratch | Add `load_cases()` with explicit XLSX dispatch and one current-domain Pydantic `TypeAdapter`. |

### `dataset/export.py` XLSX integration

Status: implemented; 198 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | No XLSX export behavior or code existed to reuse. |
| `integration/p1-new` | Preserve Case/Turn export, the XLSX media type, and safe versioned filenames. |
| `integration/p1-new` | Reuse no code directly; workbook generation now belongs to the approved format adapter. |
| `integration/p1-new` | Reject repository lookup, publication checks, HTTP streaming, attachment headers, ETag, and cache handling. |
| Current refactor | Reuse `ExportedDataset`, identity validation, safe filename normalization, and explicit dispatch structure. |
| From scratch | Add the small XLSX encoding branch and round-trip metadata tests. |

### Atomic Dataset and Version persistence

Status: implemented; 202 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Reject separate Dataset and DatasetVersion saves for imports because they are not atomic. |
| `integration/p1-new` | Preserve the atomic Dataset-plus-draft insertion behavior and transaction shape. |
| `integration/p1-new` | Adapt the operation to the current schema, canonical serialization, and both draft and published versions. |
| `integration/p1-new` | Reject draft-only policy from the storage layer. |
| Current refactor | Reuse `_connect()` transaction handling and existing schema conventions directly. |
| From scratch | Add identity validation plus rollback, draft, and published-version tests. |

### `application/dataset_management.py`

Status: implemented; 203 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve catalog, draft, Case editing, copying, publication, lookup, and JSON exchange behavior. |
| `goal/p1-demo` | Reuse simple repository lookup and orchestration method bodies where they already fit the approved boundaries. |
| `goal/p1-demo` | Rewrite import/export composition and reject local time helpers, the old export wrapper, and duplicate Dataset validation. |
| `integration/p1-new` | Preserve atomic XLSX import into a new Dataset draft. |
| `integration/p1-new` | Reuse no application code directly because it mixes obsolete domain fields and Excel mechanics. |
| Current refactor | Reuse versioning, loading, export, shared UTC time, and repository operations directly. |
| From scratch | Add the `DatasetManagement` application class and focused JSON/XLSX workflow tests. |
| Removed | `seed()`; Demo bootstrap data does not belong to Dataset management. |

### `demo/bootstrap.py`

Status: implemented; 206 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve idempotent startup seeding of the loan demonstration Dataset and publication. |
| `goal/p1-demo` | Move the two existence checks out of `DatasetService.seed()`. |
| `integration/p1-new` | No distinct behavior or better implementation to reuse. |
| Current refactor | Reuse atomic initial persistence when storage is empty and ordinary version persistence for a partial seed. |
| From scratch | Add one bootstrap function plus empty, repeated, and partial-storage tests. |

### `control_plane/service.py` Dataset caller migration

Status: implemented; 206 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve demo bootstrap, launch-time Dataset resolution, overview counts, and Dataset summaries. |
| `goal/p1-demo` | Reuse evaluation behavior and repository queries directly. |
| `goal/p1-demo` | Replace `DatasetService` construction and reject its `seed()` call. |
| `integration/p1-new` | Reuse no code; its unrelated Target registry and legacy domain expansion are outside this migration. |
| Current refactor | Reuse `DatasetManagement` and `ensure_demo_dataset()` directly. |
| From scratch | No algorithm; synchronize the one server caller with the renamed attribute. |

The application attribute is named `dataset_management`, not `datasets`, because
`EvaluationService.datasets()` already owns the Dataset-summary query name.

### `server/routes/datasets.py` Dataset caller migration

Status: implemented; 270 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve Dataset routes and the JSON response used by the current Web UI. |
| `goal/p1-demo` | Adapt route behavior without retaining the monolithic Server module. |
| `integration/p1-new` | Adapt bounded XLSX upload and streamed download behavior only. |
| Current refactor | Reuse `DatasetManagement` JSON/XLSX import and export contracts. |
| From scratch | Add a capability router, typed dependencies, structured errors, and focused route tests. |

### `domain/case.py` recovered Turn-input invariant

Status: implemented; 208 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve the rule that every Case Turn must contain input. |
| `goal/p1-demo` | Reuse no code directly because the old check ran too late during Dataset publication. |
| `integration/p1-new` | No better behavior or implementation to reuse. |
| Current refactor | Reuse `CaseTurn` and its existing Pydantic field-validation style. |
| From scratch | Add one construction-time invariant and one focused domain test. |

### Old `case/` package removal

Status: implemented; 206 tests passing

| Source | Decision |
| --- | --- |
| `goal/p1-demo` | Preserve only behavior already migrated from `service.py` and `import_export.py` into the approved Dataset and application modules. |
| `goal/p1-demo` | Move nonempty Turn input to `domain/case.py`; retain nonempty publication in versioning/application workflows; reject duplicate validation and the obsolete JSON Schema restriction. |
| `integration/p1-new` | Retain no remaining code from its old `case/` package; useful XLSX behavior was already rewritten behind current domain contracts. |
| Current refactor | Migrate repository and multi-turn test setup from `DatasetService` to `DatasetManagement`. |
| Removed | `tests/test_case_validation.py` and the complete `src/agentgate/case/` package; no compatibility alias. |

## 9. Test Plan

### Versioning

- draft from no base starts empty;
- draft from a published base preserves Case IDs and content;
- Case edit preserves identity and Case copy creates identity;
- remove/reorder reject unknown or duplicate IDs;
- publication requires a draft and at least one Case;
- publication receives rather than calculates its version number;
- content hashes remain stable and published versions immutable.

### Formats

- JSON round trips preserve DatasetVersion equality;
- XLSX round trips preserve current Case, Turn, and Expectation payloads;
- multi-turn Cases and each implemented Expectation kind round trip;
- XLSX errors identify sheet, row, and field;
- unsupported format versions fail explicitly;
- JSON-valued spreadsheet cells are canonical and deterministic;
- malformed values fail before persistence.

### Application and Regression

- existing Dataset workflows pass through the new application module;
- identity conflicts and stale drafts fail explicitly;
- existing API and Web contracts remain unchanged;
- risky/fixed demo Runs use exact published DatasetVersions;
- all backend tests pass;
- Web typecheck/build run after required import changes;
- Playwright limitations are reported honestly if host libraries remain unavailable.

## 10. Dependency Rule

This phase may add `openpyxl`. It does not add an ORM, migration framework, Redis,
Celery, PostgreSQL driver, or object-storage SDK.

```text
domain <- dataset <- application -> storage/repository.py
```

`domain/`, `dataset/`, and `application/` never import `storage/sqlite.py` directly.

## 11. Completion Gate

Dataset work is complete when:

- `src/agentgate/case/` no longer exists;
- reusable mechanics live under `dataset/`;
- workflows live under `application/dataset_management.py`;
- JSON and XLSX import/export are real and tested;
- draft publication is immutable and uses the repository's atomic operation;
- Runs resolve exact published versions;
- backend tests and required API/Web checks pass;
- no deferred empty scaffolds are introduced.
