# Single-Case Rerun Refactor Design

## Status

Approved design record for implementing Single-Case rerun on
`review/refactor-1-architecture`. This document follows the module ownership in
`docs/architecture-review-ledger.md`; it does not revive file ownership from the archived
P1 design records.

## Goal

Preserve the verified Single-Case rerun behavior while placing orchestration, execution,
and comparison logic in the refactor architecture's intended modules.

```text
Completed parent Run
  -> choose one Case from the parent's immutable Dataset snapshot
  -> choose an exact Target version (latest by default)
  -> reuse parent Evaluators, MetricPlan, and GateSpec
  -> create and execute an independent child Run for that Case
  -> compare parent and child Results
  -> return a report without modifying the parent Run, Trace, or Results
```

## Scope

- Implement Single-Case rerun only.
- Preserve the existing HTTP request and response behavior from
  `feature/single-case-rerun`.
- Preserve parent/root Run lineage and the selected Case identity.
- Preserve backward compatibility for Run snapshots already stored by P1.
- Preserve the existing Chinese Web flow and comparison terminology.
- Add focused Result comparison tests and retain full API/browser coverage.

The following are out of scope:

- Regression Dataset creation or management.
- Excel import/export.
- Automatic Dataset generation.
- General A/B experiments or statistical significance.
- A complete repository-wide `refactor-1` migration.
- Database schema migration; the SQLite JSON payload remains sufficient.

## Module Ownership

| Responsibility | Owner |
| --- | --- |
| Run lineage and immutable rerun identity | `domain/run.py` |
| Selected-Case execution and snapshot compatibility | `run/` |
| Create and execute the rerun use case | `application/run_management.py` |
| Load canonical reports and comparison inputs | `application/result_reader.py` |
| Pure Result pairing and change classification | `result/comparison.py` |
| SQLite persistence | `storage/` |
| HTTP transport and status-code mapping | `server/` |
| User interaction and rendering | `web/` |

The application layer may depend on Run and Result capabilities. Result comparison must
not read repositories, create Runs, execute Agents, or construct HTTP responses.

## Domain Contract

The rerun child `Run` records:

```python
parent_run_id: str | None
root_run_id: str | None
rerun_case_id: str | None
```

The immutable execution input records an optional Case selection:

```python
selected_case_ids: tuple[str, ...] | None
```

- `None` means execute the complete Dataset and must remain compatible with old snapshot
  hashes.
- A rerun contains exactly one Case ID.
- The ID must exist in the snapshotted Dataset version.
- The child stores the complete original Dataset version; it must not create a synthetic
  one-Case Dataset.
- First rerun: parent and root both identify the source Run.
- Repeated rerun: parent identifies the immediate Run and root remains the first Run.

The architecture ledger proposes `RunManifest` as the eventual immutable execution record.
This increment may retain the working `RunSnapshot` type if the broader Manifest contract is
not yet implemented; it must keep the selected-Case field behind one Run-owned boundary so
that a later rename is mechanical.

## Application Flow

`application/run_management.py` owns the command workflow:

1. Load the source Run and require `completed` status.
2. Resolve the Case from the source Run's immutable Dataset content.
3. Resolve and validate the requested exact Target version; use the catalog's explicit
   latest version when omitted.
4. Reuse the source Evaluator specifications, primary Evaluator IDs, MetricPlan, and
   GateSpec.
5. Create a child Run with lineage and one selected Case.
6. Execute and persist the child through the same Run execution boundary as a normal Run.

It never reads a current Dataset draft or substitutes a newer Dataset version.

`application/result_reader.py` owns the query workflow:

1. Load the rerun, its direct parent, and the rerun Case metadata.
2. Require a completed rerun with valid lineage.
3. Load canonical parent and child Results for that Case.
4. Delegate pure comparison to `result/comparison.py`.
5. Return lineage, Target versions, Case identity, per-Evaluator changes, and the overall
   classification.

## Result Comparison

`result/comparison.py` pairs Results by `evaluator_id` and produces these per-Evaluator
classifications:

| Classification | Rule |
| --- | --- |
| `improved` | FAIL/REVIEW becomes PASS, or two score-bearing Results have a higher new score |
| `regressed` | PASS becomes FAIL/REVIEW, or two score-bearing Results have a lower new score |
| `unchanged` | Outcome and score are equal |
| `incomparable` | Either side is ERROR or NOT_APPLICABLE, or one side is missing |

Overall classification:

- both improvement and regression -> `mixed`;
- no regression and at least one improvement -> `improved`;
- no improvement and at least one regression -> `regressed`;
- every comparable item unchanged -> `unchanged`;
- otherwise only incomparable items -> `incomparable`.

Comparison preserves both original Result values and does not reinterpret ERROR or
NOT_APPLICABLE as Agent quality changes.

## API and Web Compatibility

Keep these endpoints:

```text
POST /api/runs/{run_id}/cases/{case_id}/rerun
GET  /api/runs/{rerun_run_id}/comparison
```

The POST body remains:

```json
{"target_version": "loan-agent-v2-fixed"}
```

The Web behavior remains:

- one rerun action per Case group;
- latest Target version selected by explicit `is_latest` metadata;
- original report remains visible;
- comparison renders beneath it;
- the child Run can be opened as a complete report and rerun again.

## Errors

| Condition | Behavior |
| --- | --- |
| Source Run missing | 404 |
| Case absent from source snapshot | 404 |
| Target version unknown | 422 |
| Source Run not completed | 422 |
| Comparison requested for a normal Run | 422 |
| Rerun not completed | 422 |
| Missing parent Run or corrupt lineage | fail closed; do not fabricate comparison |

An invalid request must not create a child Run, Trace, or Result.

## Compatibility Strategy

The refactor branch may temporarily expose compatibility imports or a thin facade for P1
callers. A compatibility layer may delegate only; it must not retain duplicate rerun or
comparison algorithms. Removal of the old `control_plane` and `run/core.py` entry points is
owned by the broader repository refactor, not this feature increment.

## Verification

- Old full-Dataset Run snapshots still validate and execute every Case.
- A child rerun executes and persists exactly one Case's Trace and Results.
- Dataset edits after the parent Run do not change the rerun Case.
- Evaluator, MetricPlan, and GateSpec are byte-equivalent to the parent's configuration.
- Repeated reruns preserve direct-parent and root lineage.
- Result comparison covers improved, regressed, mixed, unchanged, incomparable, and
  missing-result cases.
- ERROR and NOT_APPLICABLE never count as improvement or regression.
- Original Runs, Results, and Traces remain unchanged.
- Python unit/API tests, frontend type checking, production build, and browser scenarios
  all pass.

