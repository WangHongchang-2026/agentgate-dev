# AgentGate Refactor-1 Implementation Plan

## 1. Scope And Authority

This plan reorganizes the working behavior on Git branch `goal/p1-demo` into the
architecture defined by [`architecture.md`](architecture.md).

```text
goal/p1-demo                         refactor-1
working customer-demo behavior  ->  maintainable AgentGate structure
```

`integration/p1-new` is a team member's independent implementation. It is review input
only and is not the base of this refactor. Reuse decisions for it are made separately
after refactor-1 is stable.

Authority order:

1. `docs/product-requirements-zh.md`: required product behavior.
2. `docs/architecture.md`: target structure and dependency direction.
3. `docs/architecture-review-ledger.md`: detailed architecture decisions.
4. `goal/p1-demo` code and tests: inherited behavior that must be preserved.
5. Empty scaffold files carry no architectural authority.

## 2. Refactor Rules

1. Refactor structure before adding product features.
2. Preserve externally visible P1 behavior unless a confirmed decision replaces it.
3. Move tests with behavior and leave the suite passing after each phase.
4. Do not maintain old and new domain models in parallel.
5. Do not move empty scaffold modules into the new structure.
6. Do not mix `integration/p1-new` work into refactor commits.
7. Preserve existing uncommitted Web work and reconcile it during the Web phase.
8. Add dependencies and modules only for behavior that is actually implemented.

Actions used below:

- **Keep:** retain responsibility and behavior.
- **Rename/Move:** retain behavior under the confirmed boundary.
- **Split:** separate mixed responsibilities.
- **Merge:** fold a small helper into its owner.
- **Remove:** delete obsolete, duplicate, or empty scaffolding after references are gone.
- **Defer:** document the boundary without implementing it in this refactor.

## 3. Baseline Behavior To Preserve

- Dataset draft, edit, copy, reorder, publish, archive, import, and export workflows.
- Immutable Dataset versions and reproducible Run snapshots.
- Published-Dataset and evaluator preflight validation.
- Deterministic loan demo with a failing risky version and passing fixed version.
- Per-turn evaluator execution, dependencies, memoization, and error Results.
- Existing deterministic Rule evaluators and failure attribution.
- Metric aggregation, release-gate decision, and Run report.
- SQLite persistence for Datasets, Runs, Traces, Results, and demo business state.
- OTLP/HTTP ingestion and canonical Trace conversion.
- FastAPI, CLI, and Web paths for running the demo and reading results.

Before structural edits, run the complete baseline suite and record the command and
result.

## 4. Backend File Map

### Domain

| P1 source | Action | Refactor-1 destination |
| --- | --- | --- |
| `domain/base.py` | Keep | `domain/base.py` |
| `domain/case.py` | Split | `domain/case.py` for individual Cases; `domain/dataset.py` for Dataset aggregates and versions |
| `domain/expectation.py` | Keep | `domain/expectation.py` |
| `domain/evaluation.py` | Rename | `domain/evaluator.py` |
| `domain/run.py` | Split/expand | `domain/run.py`, `domain/target.py`; replace `RunSnapshot` with `RunManifest` |
| `domain/trace.py` | Keep/expand | `domain/trace.py` |
| `domain/result.py` | Keep | `domain/result.py` |
| `domain/metric.py` | Keep | `domain/metric.py` |
| `domain/gate.py` | Keep | `domain/gate.py` |
| `domain/report.py` | Keep | `domain/report.py` |
| none | Add | `domain/artifact.py`, `domain/skill_analysis.py` |

`domain/__init__.py` is updated last so it exports only the confirmed public API.

### Dataset

| P1 source | Action | Refactor-1 destination |
| --- | --- | --- |
| `case/import_export.py` | Split | `dataset/loader.py`, `dataset/export.py`, `dataset/formats/json.py` |
| `case/service.py` | Move/split | `application/dataset_management.py`, `dataset/versioning.py` |
| `case/validation.py` | Split/remove | Case invariants in `domain/case.py`; Dataset invariants in `domain/dataset.py`; workflow/preflight checks in application |
| empty `case/customer/` | Remove | Recreate only for a real customer format |
| empty `case/public_benchmarks/` | Remove/defer | Add benchmark adapters only when implemented |
| none | Add when needed | `dataset/sampling.py` and implemented files under `dataset/formats/` |
| none | Defer | `dataset/generation/` |

### Evaluator

| P1 source | Action | Refactor-1 destination |
| --- | --- | --- |
| `evaluator/base.py` | Rename | `evaluator/evaluator_protocol.py` |
| `evaluator/runner.py` | Rename/adapt | `evaluator/executor.py` |
| `evaluator/models.py` | Keep | `evaluator/models.py` |
| `evaluator/calc_score.py` | Merge | Private executor/rule finalization behavior |
| `evaluator/observations.py` | Move | `evaluator/rule/observations.py` |
| `evaluator/operators/` | Move | `evaluator/rule/operators.py` |
| `evaluator/rules/*.py` | Move | `evaluator/rule/*.py` |
| `evaluator/registry.py` | Remove after adaptation | Explicit composition in `application/evaluator_management.py` |
| `evaluator/validation.py` | Split | Spec invariants in domain; selected-plan preflight in application |
| `evaluator/hybrid/README.md` | Replace when implemented | `evaluator/hybrid.py` |
| `evaluator/llm_judge/README.md` | Replace when implemented | `evaluator/judge/` |
| empty `evaluator/external/` | Remove | Real external adapters belong in `integrations/` |

Preserve per-turn checks, dependency resolution, memoization, evaluator version checks,
sanitized errors, and independent error Results while removing global registration.

### Trace And Run

| P1 source | Action | Refactor-1 destination |
| --- | --- | --- |
| `trace/normalizer.py` | Keep | `trace/normalizer.py` |
| `trace/receivers/otlp_http.py` | Move | `integrations/observability/otlp_http_receiver.py` |
| empty Trace importers/adapters/graph/evidence/models | Remove | Add only for real integrations or analysis needs |
| none | Add | `trace/redaction.py` |
| `run/core.py` | Split | `run/engine.py`, `run/target_protocol.py`, `integrations/targets/python_function.py` |
| `run/core.py:LocalScheduler` | Remove | Direct application call or real job dispatcher |
| `run/core.py:ExternalSchedulerAdapter` | Redefine | Application/job-dispatch boundary at whole-Run level |
| empty `run/snapshot.py` | Replace | `run/manifest.py` |
| empty `run/lifecycle.py`, `run/models.py`, `run/scheduler.py` | Remove | Responsibilities already belong to domain/application/integrations |
| empty `run/targets/`, `run/external/` | Remove/recreate | Real adapters under `integrations/targets/` |
| none | Add when exercised | `run/process_manager.py`, `run/retry.py`, `run/artifacts.py` |

### Result

| P1 source | Action | Refactor-1 destination |
| --- | --- | --- |
| `result/calc_metrics.py` | Rename | `result/metrics.py` |
| `result/gate.py` | Keep | `result/gate.py` |
| `result/service.py` | Rename | `result/report.py` |
| empty `result/compare.py` | Remove/recreate | `result/comparison.py` when comparison is implemented |
| empty `result/export/` | Remove | Real external outputs belong in integrations |

### Application, Storage, Server, CLI, And Demo

| P1 source | Action | Refactor-1 destination |
| --- | --- | --- |
| `control_plane/service.py` | Split/remove | Capability-oriented modules under `application/` |
| `storage/base.py` | Rename/expand | `storage/repository.py` |
| `storage/sqlite.py` | Keep/refactor | `storage/sqlite.py` with indexed manifest asset references |
| none | Add when Artifact exists | `storage/artifacts.py` |
| `server/application.py` | Split | `server/app.py`, dependencies, errors, and `server/routes/*.py` |
| `cli/application.py` | Split | `cli/main.py`, `run_commands.py`, `dataset_commands.py`, `result_commands.py` |
| `demo/loan.py`, `demo/provider.py` | Move | `examples/loan_approval/` |

Application destinations are `run_management.py`, `dataset_management.py`,
`target_catalog.py`, `evaluator_management.py`, `result_reader.py`, and
`lineage_queries.py`. Server and CLI must call these shared use cases.

### Removed Or Deferred Top-Level Packages

| P1 package | Decision |
| --- | --- |
| `experiment/` | Remove one-line placeholders; introduce focused `ab_test/` only when needed. |
| `lineage/` | Remove placeholders; use RunManifest references, indexes, and lineage queries. |
| `queue/` | Remove placeholders; use a real job dispatcher integration. |
| `optimizer/` | Retain as a documented future boundary; defer implementation design. |
| `control_plane/` | Remove after its use cases move to `application/`. |

## 5. Web Refactor Map

The Web phase starts from `goal/p1-demo` behavior plus the current uncommitted Web work.
Those changes must be incorporated rather than overwritten.

| Current area | Action | Destination |
| --- | --- | --- |
| broad `App.vue` workflow/navigation | Split | `layouts/AppLayout.vue`, router, and capability pages |
| manual navigation | Replace | `router/index.ts` using Vue Router |
| Dataset UI | Keep/adapt | Dataset page, components, and `useDatasetWorkspace.ts` |
| launch/progress UI | Split | Run page, components, and `useRunProgress.ts` |
| overview/result UI | Split | Overview, Result Center, and Result Detail pages |
| broad API client | Split | Transport client plus capability API modules |
| Dataset-only API types | Split/expand | Capability contracts under `types/` |
| global styles | Keep/reconcile | Tokens, base rules, and scoped feature styles |
| static Skill analysis | Add after backend contract | Skill Analysis page, components, and API |
| optimizer UI | Defer | Add only with a real backend use case |

The seven active routes remain those defined in [`web/README.md`](web/README.md).

## 6. Implementation Phases

### Phase 0: Record Baseline

- Create `refactor-1` from `goal/p1-demo` without losing unrelated working-tree changes.
- Run and record backend and Web baseline tests.
- Mark tests that depend on obsolete import paths.

Gate: risky/fixed demo, Dataset workflow, OTLP, API, CLI, and Web behavior have a recorded baseline.

### Phase 1: Domain

- Finalize domain modules, invariants, versions, manifests, and public exports.
- Add focused domain and serialization tests.

Gate: domain has no feature/infrastructure imports; immutability and hash round trips pass.

### Phase 2: Storage And Dataset

- Align repository/SQLite boundaries.
- Separate Dataset mechanics, formats, and application workflows.

Gate: Dataset and repository tests pass through the new boundaries.

### Phase 3: Evaluator And Result

- Establish Evaluator protocol, explicit composition, executor, rules, and runtime models.
- Align Metrics, Gate, Report, and Comparison modules.

Gate: risky/fixed Result counts, scores, attribution, and Gate conclusions match baseline.

### Phase 4: Trace, Target, And Run

- Separate RunEngine, manifest construction, Target protocol, adapters, and OTLP handling.
- Add redaction; add process/retry/artifact modules only with exercised behavior.

Gate: an end-to-end Run persists its exact manifest, Traces, Results, Metrics, Gate, and Report.

### Phase 5: Application, Server, And CLI

- Replace `control_plane/` with application use cases.
- Split FastAPI and CLI transports around those shared use cases.

Gate: API and CLI produce equivalent persisted results without direct evaluation or SQL logic.

### Phase 6: Web

- Reconcile existing Web changes and split routing, layout, pages, components, state, APIs, and types.
- Connect active pages to real FastAPI responses.

Gate: typecheck, unit tests, build, and desktop/mobile Playwright workflows pass.

### Phase 7: Cleanup

- Remove empty scaffolds, obsolete imports, stale dependencies, and generated caches.
- Run boundary checks and complete backend/Web suites.
- Compare final demo output with the Phase 0 baseline.

Gate: no duplicate domain models or obsolete packages remain and all acceptance tests pass.

## 7. Commit Order

```text
refactor(domain)
refactor(storage)
refactor(case)
refactor(evaluator)
refactor(result)
refactor(run)
refactor(application)
refactor(server)
refactor(cli)
refactor(web)
chore(cleanup)
```

Each commit must be independently reviewable and must not include team branch features.

## 8. Team Branch Review After Refactor

After refactor-1 passes all gates, review `integration/p1-new` using:

```text
Capability | Needed behavior | Test quality | Architectural fit | Port/reimplement/reject
```

Potential candidates include JSON Schema evaluation, Excel handling, HTTP Target
execution, Trace correlation, single-Case rerun, regression workflows, and selected Web
components. This later review does not change the refactor baseline.
