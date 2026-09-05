# Phase 2 Storage and Dataset Implementation Plan

Status: proposed for file-by-file review

Authority:

1. `docs/architecture.md`
2. `docs/architecture-review-ledger.md`
3. `docs/refactor-implementation-plan.md`
4. This Phase 2 plan

The implementation starts from `refactor-1`. Team branches are review inputs only and
are not merged wholesale.

## 1. Goal

Refactor the working P1 Dataset flow without changing its user-visible behavior:

```text
Web / CLI / API
       |
       v
application/dataset_management.py     workflow and permissions boundary
       |
       +----> dataset/                 pure Dataset mechanics and formats
       |
       v
storage/repository.py                 persistence contract
       |
       v
storage/sqlite.py                     POC persistence implementation
```

The completed phase must support:

- Dataset catalog create, read, update, archive, and copy;
- one editable draft per Dataset;
- Case add, update, copy, remove, and reorder within a draft;
- immutable numbered publication;
- single-turn and multi-turn Cases;
- canonical JSON import/export;
- Excel `.xlsx` import/export for business-unit data exchange;
- exact published DatasetVersion retrieval for an Evaluation Run.

## 2. Terms

- **Dataset**: stable catalog identity and editable display metadata.
- **DatasetVersion**: immutable content snapshot containing ordered Cases.
- **Draft**: editable candidate for the next published version; never runnable.
- **Published version**: immutable numbered DatasetVersion selectable by a Run.
- **Case**: one single-turn or multi-turn evaluation scenario.
- **Format adapter**: converts external bytes/rows into plain structured data and back.
- **Loader**: turns format-adapter output into validated domain objects.
- **Repository**: stores and retrieves domain objects; it does not create business objects.

## 3. Final File Map

```text
src/agentgate/
├── storage/
│   ├── __init__.py
│   ├── repository.py
│   └── sqlite.py
├── dataset/
│   ├── __init__.py
│   ├── loader.py
│   ├── export.py
│   ├── versioning.py
│   └── formats/
│       ├── __init__.py
│       ├── json.py
│       └── xlsx.py
└── application/
    ├── __init__.py
    └── dataset_management.py
```

Deferred until a real caller is implemented:

```text
dataset/sampling.py
dataset/generation/
storage/artifacts.py
```

Do not create empty placeholder files for deferred capabilities.

## 4. Add, Rename, Move, and Remove

| Current | Action | Destination |
| --- | --- | --- |
| `storage/base.py` | Rename and tighten | `storage/repository.py` |
| `storage/sqlite.py` | Refactor | `storage/sqlite.py` |
| `case/import_export.py` | Split | `dataset/loader.py`, `dataset/export.py`, `dataset/formats/json.py` |
| none | Add | `dataset/formats/xlsx.py` |
| `case/service.py` | Split | `dataset/versioning.py`, `application/dataset_management.py` |
| `case/validation.py` | Remove after migration | Domain and application boundaries already own its valid rules |
| empty `case/customer/` | Remove | Recreate only for an implemented external format |
| empty `case/public_benchmarks/` | Remove | Add real benchmark integrations later |
| `case/` | Remove | Replaced by `dataset/` |

No compatibility aliases from `agentgate.case` or `agentgate.storage.base` are retained.

## 5. Module Contracts

### 5.1 `storage/repository.py`

Rename `AgentGateRepository` only if file-by-file review finds a clearer name. For POC,
one Protocol remains acceptable because all capabilities use the same SQLite unit.

Responsibilities:

- declare typed object-level persistence operations;
- accept and return domain models;
- expose Dataset, DatasetVersion, Run, Trace, and Result persistence needed today;
- expose one atomic operation that replaces an expected draft with an already-built
  published DatasetVersion;
- remain independent of SQLite, FastAPI, CLI, and Web types.

It must not:

- assign Dataset version numbers;
- construct or modify domain objects;
- validate Dataset business rules;
- calculate Results or Metrics;
- store Demo Agent business state.

The publication operation should express storage atomicity, not business logic:

```python
replace_dataset_draft(
    expected_draft_id: str,
    published: DatasetVersion,
) -> None
```

The application/versioning layers build `published`; SQLite verifies the expected draft
still exists and atomically inserts the publication and deletes that draft.

### 5.2 `storage/sqlite.py`

Responsibilities:

- implement `AgentGateRepository`;
- initialize the POC schema;
- enable foreign keys, WAL mode, and a bounded busy timeout;
- keep transactions short and explicit;
- store complete domain objects as canonical JSON payloads;
- keep selected relational columns for identity, ordering, filtering, constraints, and
  indexes;
- reconstruct domain objects with Pydantic so corrupted persisted data fails loudly;
- enforce published-version immutability and one-draft-per-Dataset constraints;
- perform draft replacement and publication in one transaction.

Required cleanup:

- remove DatasetVersion construction and `uuid4()` from SQLite;
- remove `business_state` table and methods from AgentGate storage;
- move Demo loan state behind a Demo-owned store so existing demonstrations still run;
- avoid `INSERT OR REPLACE` where replacement can hide identity or immutability errors;
- use explicit insert/update conflict behavior.

Schema migration is not required. POC databases are disposable, and this refactor does
not provide backward compatibility.

### 5.3 `dataset/versioning.py`

Pure functions for Dataset draft transformations:

- create a draft from an optional published base;
- add or replace a Case while preserving Case identity;
- remove a Case;
- copy a Case with a new ID;
- reorder Cases only when every Case appears exactly once;
- build a published DatasetVersion from a draft and explicit next version number;
- calculate change information needed by the application.

Rules:

- functions return new immutable domain objects;
- no repository calls, SQL, HTTP, or global state;
- timestamps, IDs, and next version numbers are passed in when determinism matters;
- domain constructors remain the final invariant check;
- publication rejects an empty Dataset and a non-draft source.

### 5.4 `dataset/formats/json.py`

Own the external canonical JSON envelope and byte/string conversion:

```text
format = agentgate.dataset
format_version = 1
dataset = Dataset payload
version = DatasetVersion payload
```

It checks envelope syntax and supported format version. It does not persist, publish,
or make application decisions.

### 5.5 `dataset/formats/xlsx.py`

Implement the business-unit spreadsheet boundary with `openpyxl`.

Workbook structure:

- `dataset`: Dataset metadata and format version;
- `cases`: one row per Case with category, difficulty, tags, notes, and initial state;
- `turns`: one row per CaseTurn with stable Case ID, turn order, input, and notes;
- `expectations`: one row per typed expectation with Case ID, turn ID, kind, and JSON
  configuration.

JSON-valued cells use canonical JSON. IDs are explicit; row position never becomes
identity. Import errors include sheet, row, and field. Formula execution, macros, merged
cell semantics, and arbitrary customer templates are out of scope.

### 5.6 `dataset/loader.py`

- select the implemented format adapter from an explicit format argument;
- parse external input;
- create `Dataset`, `DatasetVersion`, `Case`, `CaseTurn`, and Expectation domain objects;
- return validation errors with stable locations;
- reject unsupported format versions and unknown expectation kinds.

It does not save imported objects or resolve identity conflicts. Those are application
workflow decisions.

### 5.7 `dataset/export.py`

- verify Dataset and DatasetVersion identities match;
- create the canonical export representation;
- delegate JSON or XLSX encoding to `dataset/formats/`;
- return bytes plus media type and suggested filename.

It does not query storage or format HTTP responses.

### 5.8 `application/dataset_management.py`

Move the current `DatasetService` workflows here and rename the class only during its
file-level review.

Responsibilities:

- coordinate catalog CRUD and archive behavior;
- resolve not-found and conflict conditions;
- call pure `dataset/versioning.py` transformations;
- determine the next published version number;
- require a nonempty valid draft before publication;
- call the repository atomic draft-replacement operation;
- coordinate import identity policy and persistence;
- coordinate export retrieval and encoding;
- resolve an exact published DatasetVersion for Run manifest construction.

It must not contain SQL, parse XLSX rows, execute an Agent, or calculate evaluation
Results.

## 6. Validation Ownership

```text
External syntax / workbook shape       dataset/formats/
External-to-domain conversion          dataset/loader.py
Field and aggregate invariants         domain/case.py, domain/dataset.py
Draft workflow and publication rules   application/dataset_management.py
Evaluator availability/preflight       later application Run composition
SQL constraints and atomicity           storage/sqlite.py
```

`case/validation.py` is removed. In particular:

- duplicate Case/Turn/Expectation IDs belong in domain models;
- blank typed fields belong in domain models;
- “Dataset must contain at least one Case before publish” belongs in the application
  publication workflow;
- whether `MatchesJsonSchema` has an available evaluator belongs in Run preflight, not
  Dataset validity.

## 7. Implementation Sequence and Approval Gates

Follow the project rule: review one file, approve its design, implement it, run focused
tests, and only then move to the next file.

1. **Names and baseline**
   Confirm the final file map and record current Dataset repository/service tests.
2. **`storage/repository.py`**
   Rename `base.py`, remove business construction from the Protocol, and update imports.
3. **`storage/sqlite.py`**
   Implement the tightened contract, transaction behavior, pragmas, and immutable writes.
4. **Demo state extraction**
   Move `business_state` ownership out of AgentGate storage without changing demo output.
5. **`dataset/versioning.py`**
   Extract pure immutable draft and publication transformations.
6. **`dataset/formats/json.py`**
   Preserve the current canonical JSON round trip.
7. **`dataset/loader.py` and `dataset/export.py`**
   Establish format-neutral public mechanics.
8. **`dataset/formats/xlsx.py`**
   Add deterministic Excel import/export and location-rich validation errors.
9. **`application/dataset_management.py`**
   Move workflows from `case/service.py` and compose the new modules.
10. **Cleanup**
    Remove `case/`, stale imports, duplicate validation, and empty scaffolds.
11. **Transport reconciliation**
    Update existing API/CLI imports only as required to preserve behavior. Do not redesign
    server, CLI, or Web in this phase.

Each checkpoint receives its own reviewable commit when practical.

## 8. Test Plan

### Repository and SQLite

- Protocol implementation is usable by application services and test doubles.
- Dataset save/read/list/archive round trips preserve domain equality.
- only one draft exists per Dataset.
- published `(dataset_id, version)` is unique.
- published payload cannot be changed.
- replacing the wrong or stale draft fails without partial writes.
- publication insert and draft deletion are atomic.
- malformed stored payload fails domain reconstruction.
- foreign keys are enabled; concurrent POC access uses WAL and busy timeout.

### Versioning

- draft from no base starts empty;
- draft from a published base preserves Case IDs and content;
- Case edit preserves identity; Case copy creates identity;
- remove and reorder reject unknown or duplicate IDs;
- publication requires a draft and at least one Case;
- publication receives, rather than calculates, its version number;
- content hashes are stable and published versions are immutable.

### Formats

- JSON and XLSX round trips preserve DatasetVersion domain equality;
- multi-turn Cases and every implemented Expectation kind round trip;
- XLSX import reports sheet/row/field for invalid data;
- unsupported format versions fail explicitly;
- JSON-valued spreadsheet cells are canonical and deterministic;
- imported duplicate identities and malformed typed values fail before persistence.

### End-to-end regression

- existing Dataset service tests pass through the new application path;
- existing Dataset API and Web contracts remain unchanged;
- risky/fixed demo Runs use exact published DatasetVersions;
- all backend tests pass;
- Web typecheck and build pass after required import changes;
- Playwright remains environment-dependent and must be reported honestly.

## 9. Dependency Rule

Phase 2 may add `openpyxl` for `.xlsx` support. No ORM, migration framework, Redis,
Celery, PostgreSQL driver, or object-storage SDK is added in this phase.

Dependency direction:

```text
domain <- dataset <- application -> storage repository protocol
                                   -> storage SQLite implementation at composition root
```

`domain/`, `dataset/`, and `application/` never import `storage/sqlite.py` directly.

## 10. Completion Gate

Phase 2 is complete when:

- no `src/agentgate/case/` package remains;
- no `src/agentgate/storage/base.py` remains;
- SQLite constructs no Dataset or DatasetVersion business transition;
- AgentGate storage contains no Demo Agent business state;
- JSON and XLSX Dataset import/export are real and tested;
- published versions remain immutable and Runs resolve an exact version;
- backend tests pass and required API/Web contract checks show no regression;
- the worktree is clean and commits are pushed to `refactor-1` after review.
