# Dataset and Case Management Plan

## Goal

Build a real SQLite-backed Dataset and Case workflow that can be tested from the Chinese
Web UI:

```text
Create Dataset
  -> add or edit Cases
  -> validate expected outcomes
  -> publish an immutable Dataset version
  -> launch an evaluation with that exact version
  -> inspect expected versus actual results and Trace
  -> create a new version from a failed Case
```

The editor is part of the vertical slice. It is how we verify that the Case model is
understandable without editing Python.

## Implementation checkpoint — 2026-08-16

Checkpoints 1–3 are implemented:

- Dataset identity, immutable published versions, editable drafts, typed single/multi-turn
  Cases, expectations, validation, canonical JSON, and content hashes are Pydantic domain
  models.
- DatasetService and SQLite implement catalog CRUD, archive, copy, draft lifecycle, Case
  save/copy/remove/reorder, publish, and import/export.
- FastAPI exposes the Dataset workflow. Evaluation launch requires an explicit published
  Dataset version, which is embedded in the immutable RunSnapshot.
- The Chinese `/datasets` workspace uses real APIs. It has Dataset, Case, and structured
  Case-editor columns; version controls; field-level publish issues; and a version-aware
  evaluation launch.
- Results show expected and actual values. Trace detail shows each turn's input, output,
  state, and spans.
- The loan demo is seeded as published version 1. No compatibility path for disposable
  pre-versioning POC data is included.

Verification:

```bash
python3 -m pytest -q
cd web
npm run typecheck
npm run build
npm run test:e2e
```

The browser suite covers desktop and Pixel 7 layouts with a dedicated SQLite database.
Excel import/export and single-Case rerun were implemented after checkpoints 1–3.
Automatic generation and the regression-set workflow remain deferred as described below.

## Original gap (resolved)

Before this slice, `domain/case.py` had only runnable data objects, the demo Dataset was
hard-coded, `src/agentgate/case/` contained empty scaffolds, SQLite did not persist
Datasets, and the Web UI could neither inspect nor edit Cases. The implementation
checkpoint above closes this gap.

## Terms

```text
Dataset
  Stable identity and display information

DatasetVersion
  Immutable numbered content used by a Run; contains Cases

Case
  One test scenario with input, setup, metadata, and expected outcomes

Draft
  Editable candidate for the next DatasetVersion; never used by a Run

Published version
  Immutable DatasetVersion selectable by a Run
```

A new version continues the same Dataset history. Copying a Dataset creates a new Dataset
identity and an independent history.

## Version rules

- Published DatasetVersions are immutable.
- Editing a published version creates a draft based on it.
- Publishing allocates the next integer version.
- Runs accept only published versions and embed canonical content in RunSnapshot.
- Historical Runs never reread live Dataset data.
- A Case ID stays stable when that Case is edited across Dataset versions.
- Copying a Case creates a new Case ID.
- Removing a Case affects only the draft.
- Deleting a Dataset archives it; referenced published versions remain readable.
- Current POC data is disposable, so no migration from the hard-coded form is required.

## Domain model

### Increment 1: single-turn management

`src/agentgate/domain/case.py` defines:

```text
Dataset
├── id, name, description
├── archived
└── timestamps

DatasetVersion
├── id, dataset_id, version
├── status: draft | published
├── based_on_version
├── cases
├── notes
└── timestamps

Case
├── id, name, input, initial_state
├── category: positive | negative | boundary
├── difficulty: easy | medium | hard
├── tags and notes
├── expected_skill and expected outcomes
├── required_tools and forbidden_tools
└── policy_rules
```

`RunSnapshot.dataset` stores the selected immutable DatasetVersion.

### Increment 2: multi-turn Cases

Use typed turns rather than an arbitrary conversation dictionary:

```text
Case
└── turns: CaseTurn[]
      ├── id and user input
      ├── expected skill and expected outcomes
      ├── required/forbidden tools
      └── notes
```

A single-turn Case has one CaseTurn, keeping one execution model. Trace spans carry a
`turn_id`; detailed checks identify the related turn and expected outcome. Session state
is preserved between turns.

This was implemented after the single-turn persistence/editor flow and uses the same
published DatasetVersion schema.

## Validation

`src/agentgate/case/validation.py` checks before publishing:

- a draft contains at least one Case;
- Case IDs are unique;
- Case/turn IDs and executable inputs are present;
- category and difficulty values are supported;
- expected paths and conditions are valid and implemented;
- required and forbidden tool sets do not overlap;
- multi-turn references point to existing turns.

Pydantic validates individual objects. This module validates relationships and whether
the entire Dataset can be published.

## Application service

Add `src/agentgate/case/service.py` with workflows shared by HTTP and future CLI:

- create, list, read, rename, archive, and copy a Dataset;
- list and read versions;
- create or discard a draft;
- add, edit, copy, reorder, and remove draft Cases;
- validate and publish a draft;
- import/export canonical JSON;
- resolve a published DatasetVersion for a Run.

The service does not execute evaluations. `control_plane/service.py` selects a published version
and passes it to RunEngine.

## Persistence

`storage/base.py` and `storage/sqlite.py` are extended as follows.

```text
datasets
  id, name, description, archived, created_at, updated_at

dataset_versions
  id, dataset_id, version, status, based_on_version,
  payload, content_sha256, created_at, published_at
```

For the POC, Cases remain in the version's canonical JSON payload. This makes publishing
atomic and immutable while keeping the repository boundary suitable for PostgreSQL.

Rules:

- published versions are unique by `(dataset_id, version)`;
- at most one active draft exists per Dataset;
- published payloads and hashes cannot be updated;
- archived data remains readable through historical Runs.

## HTTP API

FastAPI delegates these operations to DatasetService:

```text
GET    /api/datasets
POST   /api/datasets
GET    /api/datasets/{dataset_id}
PATCH  /api/datasets/{dataset_id}
DELETE /api/datasets/{dataset_id}                 archive
POST   /api/datasets/{dataset_id}/copy

GET    /api/datasets/{dataset_id}/versions
GET    /api/datasets/{dataset_id}/versions/{version}
POST   /api/datasets/{dataset_id}/drafts
DELETE /api/datasets/{dataset_id}/drafts/current
POST   /api/datasets/{dataset_id}/drafts/publish

POST   /api/datasets/{dataset_id}/drafts/cases
PUT    /api/datasets/{dataset_id}/drafts/cases/{case_id}
DELETE /api/datasets/{dataset_id}/drafts/cases/{case_id}
POST   /api/datasets/{dataset_id}/drafts/cases/{case_id}/copy

GET    /api/datasets/{dataset_id}/versions/{version}/export
POST   /api/datasets/import
```

Run launch adds an explicit `dataset_version`; Dataset ID alone is not reproducible.

## Chinese Web UI

The first-class `/datasets` workspace is:

```text
Left: Dataset list        Center: Case list       Right: Case editor
├── search/status         ├── category            ├── basic information
├── create/copy/archive   ├── difficulty          ├── input or turns
└── version selector      ├── tags                ├── routing/tools
                          └── readiness           └── state/output expectations
```

Required interactions:

- create or copy a Dataset;
- select a published version or current draft;
- start a new version;
- add, edit, copy, reorder, and remove Cases;
- edit routing, tools, arguments, state, and output expectations;
- show validation errors beside fields;
- validate and publish a draft;
- launch an evaluation with the published version;
- show expected and actual values together;
- reload and see persisted data.

Use structured Element Plus controls. Raw JSON preview is useful but cannot be the only
editor.

Implemented Web files:

```text
web/src/
├── pages/DatasetWorkspace.vue
├── components/dataset/DatasetList.vue
├── components/dataset/VersionSelector.vue
├── components/dataset/CaseTable.vue
├── components/dataset/CaseEditor.vue
├── components/dataset/ExpectationEditor.vue
├── api/datasets.ts
└── types/dataset.ts
```

Multi-turn editing is implemented inside `CaseEditor.vue` because each turn shares the
same save boundary as its Case. A separate `TurnEditor.vue` can be extracted if that
component gains an independent workflow.

## Import/export and generation

Implement canonical JSON first with an explicit format version. Excel follows after the
model stabilizes because nested expectations and multi-turn Cases require a deliberate
worksheet mapping.

Automatic generation is later. Generated Cases enter a draft and follow the same review
and publish workflow.

## Code change map

```text
src/agentgate/
├── domain/case.py                     [MOD] Dataset identity/version and richer Case
├── domain/run.py                      [MOD] Snapshot selected DatasetVersion
├── case/__init__.py                   [MOD] Public Dataset service API
├── case/validation.py                 [ADD] Whole-Dataset publish validation
├── case/service.py                    [ADD] Dataset/Case/version workflows
├── case/import_export.py              [ADD] Canonical JSON import/export
├── storage/base.py                    [MOD] Dataset repository contract
├── storage/sqlite.py                  [MOD] Dataset/version persistence
├── control_plane/service.py           [MOD] Resolve stored version for Run launch
├── server/application.py              [MOD] Dataset and Case endpoints
└── demo/loan.py                       [MOD] Seed demo data through DatasetService

web/src/
├── App.vue                            [MOD] Dataset workspace navigation
├── pages/DatasetWorkspace.vue         [ADD]
├── components/dataset/*.vue           [ADD]
├── api/datasets.ts                    [ADD]
└── types/dataset.ts                   [ADD]

tests/
├── test_case_models.py                [ADD]
├── test_case_validation.py            [ADD]
├── test_dataset_service.py            [ADD]
├── test_dataset_repository.py         [ADD]
├── test_dataset_api.py                [ADD]
├── test_dataset_import_export.py      [ADD]
└── web/tests/dataset.spec.ts          [ADD]
```

Remove or replace empty scaffold files such as `case/models.py`, `case/schema.py`,
`case/loader.py`, and `case/versioning.py`; do not leave several empty modules that
appear to own the same behavior.

## Delivery checkpoints

### 1. Persisted single-turn editor — done

- Domain model, repository, DatasetService, validation, and APIs.
- Chinese Dataset/Case editor and JSON import/export.
- Existing loan data seeded as published Dataset version 1.

### 2. Run integration — done

- Run launch requires a published Dataset version.
- RunSnapshot proves version and content hash.
- Result detail shows expected and actual data.
- Editing a failed Case creates a new Dataset version.

### 3. Multi-turn — done

- Typed CaseTurn and session execution.
- Turn-aware Trace, checks, results, and editor.
- Unit, API, and browser tests.

### 4. Later capabilities

- Excel import/export. — done
- Automatic generation into a draft.
- Single-Case rerun. — done
- Regression-set workflow.

## Acceptance test

The main Playwright scenario uses only real APIs:

1. Create a Dataset in the Web UI.
2. Add a high-risk Case with expected Skill, tools, and final state.
3. Publish version 1.
4. Reload and confirm the persisted version and Case.
5. Run `loan-agent-v1-risky` and observe failed checks.
6. Inspect expected values, actual values, evidence, and Trace.
7. Start version 2, edit and publish the Case without changing version 1.
8. Confirm the historical Run still displays its version-1 snapshot.

Also test invalid Cases, publishing an empty draft, archived data, content hashing, JSON
round trips, desktop layout, and mobile editing.

## Deferred

- Public benchmark integration.
- Production scheduling.
- Full lineage graphs.
- Collaborative editing and merge handling.
- Permanent deletion of published versions referenced by Runs.
- Automatic generation until the core editor is verified.
