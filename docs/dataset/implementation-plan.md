# Dataset Implementation Plan

Status: implementation in progress

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
- Excel `.xlsx` import/export for business-unit data exchange;
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

Implement `.xlsx` exchange with `openpyxl` using four sheets:

- `dataset`: Dataset metadata and format version;
- `cases`: one row per Case with category, difficulty, tags, notes, and initial state;
- `turns`: one row per CaseTurn with Case ID, turn order, input, and notes;
- `expectations`: one row per typed expectation with Case ID, turn ID, kind, and JSON
  configuration.

JSON-valued cells use canonical JSON. IDs are explicit; row position is never identity.
Import errors identify sheet, row, and field. Macros, formula execution, merged-cell
semantics, and arbitrary customer templates are out of scope.

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
3. [next] Implement `dataset/formats/json.py` and preserve canonical JSON round trips.
4. Implement `dataset/loader.py` and `dataset/export.py`.
5. Add deterministic `.xlsx` import/export in `dataset/formats/xlsx.py`.
6. Move workflows into `application/dataset_management.py`.
7. Integrate the approved `storage/repository.py` publication operation.
8. Remove `case/`, duplicate validation, stale imports, and empty scaffolds.
9. Update existing API/CLI imports only as required; do not redesign transports or Web.
10. Run focused and complete regression suites.

Each checkpoint should produce a small reviewable commit when practical.

## 8. Test Plan

### Versioning

- draft from no base starts empty;
- draft from a published base preserves Case IDs and content;
- Case edit preserves identity and Case copy creates identity;
- remove/reorder reject unknown or duplicate IDs;
- publication requires a draft and at least one Case;
- publication receives rather than calculates its version number;
- content hashes remain stable and published versions immutable.

### Formats

- JSON and XLSX round trips preserve DatasetVersion equality;
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

## 9. Dependency Rule

This phase may add `openpyxl`. It does not add an ORM, migration framework, Redis,
Celery, PostgreSQL driver, or object-storage SDK.

```text
domain <- dataset <- application -> storage/repository.py
```

`domain/`, `dataset/`, and `application/` never import `storage/sqlite.py` directly.

## 10. Completion Gate

Dataset work is complete when:

- `src/agentgate/case/` no longer exists;
- reusable mechanics live under `dataset/`;
- workflows live under `application/dataset_management.py`;
- JSON and XLSX import/export are real and tested;
- draft publication is immutable and uses the repository's atomic operation;
- Runs resolve exact published versions;
- backend tests and required API/Web checks pass;
- no deferred empty scaffolds are introduced.
