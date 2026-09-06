# Storage Implementation Plan

Status: in progress

Implemented checkpoint:

- `storage/base.py` was renamed to `storage/repository.py` without a compatibility alias.
- `AgentGateRepository` now exposes 18 exercised persistence operations.
- Published-version lookup names are explicit.
- Draft publication accepts an already-built DatasetVersion and performs atomic
  replacement by expected draft identity.
- Result batches accept `Sequence[EvaluationResult]`.
- Demo Agent business state was removed from the repository contract and SQLite schema.
- `sqlite.py` was synchronized with this contract, but its complete file review remains
  the next checkpoint.
- `SQLiteRepository._connect()` is a real context manager: it applies foreign-key and
  busy-timeout settings per connection, commits or rolls back, and always closes.
- `SQLiteRepository._initialize()` enables WAL and creates the five-table POC schema
  with DatasetVersion and Run-status checks.

Authority:

1. `docs/architecture.md`
2. `docs/architecture-review-ledger.md`
3. `docs/refactor-implementation-plan.md`
4. This plan

The implementation starts from `refactor-1`. Team branches are review inputs only and
are not merged wholesale.

## 1. Goal

Give AgentGate one explicit persistence contract and one SQLite POC implementation:

```text
application/ and core capabilities
               |
               v
storage/repository.py       typed persistence contract
               |
               v
storage/sqlite.py           POC implementation
```

Storage persists domain objects and guarantees atomic writes. It does not create domain
objects, decide lifecycle transitions, execute evaluations, or format API responses.

## 2. Terms

- **Repository**: object-level persistence operations expressed with domain types.
- **Storage adapter**: implementation of the repository contract for one backend.
- **Canonical payload**: complete domain object serialized with canonical JSON.
- **Indexed column**: selected relational value used for identity, lookup, ordering, or
  a database constraint.
- **Atomic publication write**: insert an already-built published DatasetVersion and
  remove its expected draft in one transaction.

## 3. Final File Map

```text
storage/
├── __init__.py
├── repository.py
└── sqlite.py
```

`storage/artifacts.py` is deferred until `run/artifacts.py` produces or retrieves real
artifact bytes. Do not create an empty placeholder.

## 4. File Changes

| Current | Action | Destination |
| --- | --- | --- |
| `storage/base.py` | Rename and tighten | `storage/repository.py` |
| `storage/sqlite.py` | Refactor | `storage/sqlite.py` |
| none | Defer | `storage/artifacts.py` |

No compatibility alias from `agentgate.storage.base` is retained.

## 5. `repository.py`

Initially keep one `AgentGateRepository` Protocol. Split capability-specific protocols
only after independent consumers create real complexity.

Responsibilities:

- declare typed persistence operations used by implemented application/core modules;
- accept and return domain models;
- cover current Dataset, DatasetVersion, EvaluationRun, Trace, and EvaluationResult
  persistence;
- expose an atomic operation that replaces an expected draft with an already-built
  published DatasetVersion;
- remain independent of SQLite, FastAPI, CLI, and Web models.

Prohibited behavior:

- assigning Dataset version numbers;
- constructing or mutating domain objects;
- validating Dataset business rules;
- calculating Results, Metrics, or release gates;
- storing Demo Agent business state.

The publication operation expresses storage atomicity only:

```python
replace_dataset_draft(
    expected_draft_id: str,
    published: DatasetVersion,
) -> None
```

The Dataset/application layers construct `published`. The implementation verifies that
the expected draft still exists, inserts the published object, and removes the draft in
one transaction.

## 6. `sqlite.py`

Responsibilities:

- implement `AgentGateRepository`;
- initialize the disposable POC schema;
- enable foreign keys, WAL mode, and a bounded busy timeout;
- keep transactions short and explicit;
- store complete domain objects as canonical JSON payloads;
- keep selected relational columns for identity, filtering, ordering, constraints, and
  indexes;
- reconstruct through Pydantic so malformed stored data fails loudly;
- enforce one draft per Dataset and unique published `(dataset_id, version)` values;
- reject changes to published payloads;
- atomically replace the expected draft with a supplied publication.

Required cleanup:

- remove DatasetVersion construction, version allocation, and `uuid4()` from SQLite;
- remove the `business_state` table and repository methods;
- move loan-demo state behind a Demo-owned store while preserving demo behavior;
- replace broad `INSERT OR REPLACE` writes where they can hide identity or immutability
  errors;
- use explicit insert/update conflict behavior.

Schema migration and backward compatibility are not required. Existing POC databases
are disposable.

## 7. Ownership Rules

```text
Domain invariants                    domain/
Dataset workflow and publication    application/dataset_management.py
Dataset transformations             dataset/versioning.py
Persistence contract                storage/repository.py
SQL, constraints, transactions      storage/sqlite.py
Demo loan state                     Demo/example implementation
```

SQLite/PostgreSQL is authoritative for AgentGate Runs and Results. Redis/Celery state is
operational only and is not introduced in this phase.

## 8. Implementation Sequence

Follow the project checkpoint rule: approve one file's name and responsibility, then
review classes/functions, implement it, and run focused tests before moving on.

1. [completed] Record current repository and Dataset persistence behavior.
2. [completed] Rename `storage/base.py` to `storage/repository.py` and update imports.
3. [completed] Review each Protocol method; remove construction and Demo-state operations.
4. [completed] Connection lifecycle, pragmas, schema checks, and WAL are implemented.
5. [next] Remove the forwarding `_json()` helper and review Dataset write semantics.
6. Refactor Dataset and DatasetVersion writes and atomic draft replacement.
7. Extract Demo business state from AgentGate storage.
8. Reconcile Run, Trace, and Result methods without redesigning those capabilities.
9. Run storage, Dataset, demo, API, and full backend regression tests.

Each checkpoint should produce a small reviewable commit when practical.

## 9. Test Plan

- Dataset save/read/list/archive round trips preserve domain equality.
- one active draft exists per Dataset.
- published `(dataset_id, version)` is unique.
- published payloads cannot be changed.
- replacing a missing or stale draft fails without partial writes.
- publication insertion and draft deletion are atomic.
- malformed stored payload fails domain reconstruction.
- foreign keys, WAL, and busy timeout are enabled.
- Run, Trace, and Result round trips preserve current behavior.
- the loan demo runs with Demo-owned business state.
- all backend tests pass.

## 10. Completion Gate

Storage is complete when:

- `storage/base.py` no longer exists;
- application/core modules depend on `storage/repository.py`;
- SQLite constructs no DatasetVersion transition;
- AgentGate storage owns no Demo Agent business state;
- database constraints and atomic publication behavior are tested;
- no empty artifact-storage scaffold is introduced;
- backend tests pass and the worktree is clean.
