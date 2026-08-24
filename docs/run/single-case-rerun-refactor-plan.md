# Single-Case Rerun Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the verified Single-Case rerun workflow on the refactor architecture branch while preserving the existing API, Web behavior, persistence format, and historical Run compatibility.

**Architecture:** Run-owned types record immutable Case selection and rerun lineage; `run/` executes the selected Case; `application/run_management.py` orchestrates rerun creation; `application/result_reader.py` loads comparison inputs; and `result/comparison.py` performs pure Result comparison. The existing `control_plane.EvaluationService` remains a temporary compatibility facade and must delegate rather than duplicate these algorithms.

**Tech Stack:** Python 3.11+, Pydantic, SQLite, FastAPI, Vue 3, TypeScript, Element Plus, pytest, Playwright.

**Spec:** `docs/run/single-case-rerun-refactor-design.md`

## Global Constraints

- Base all work on `review/refactor-1-architecture` and do not include Regression Dataset, Excel, or automatic-generation changes.
- Preserve `POST /api/runs/{run_id}/cases/{case_id}/rerun` and `GET /api/runs/{rerun_run_id}/comparison` contracts.
- Preserve existing SQLite tables; all new Run fields remain in the Run JSON payload.
- Never mutate the source Run, Result, Trace, or snapshotted Dataset content.
- A rerun executes exactly one Case from the source Run snapshot and reuses Evaluator, MetricPlan, and GateSpec configuration.
- Keep old snapshots readable by excluding `selected_case_ids=None` from the snapshot hash.
- Keep compatibility facades delegation-only; do not maintain two comparison or rerun implementations.
- Use the latest Target only when explicitly identified by `is_latest`; never infer it in the Web from list order.

---

### Task 1: Add immutable Case selection and rerun lineage

**Files:**
- Modify: `src/agentgate/domain/run.py`
- Modify: `src/agentgate/run/core.py`
- Modify: `tests/test_snapshot_immutability.py`
- Create: `tests/test_selected_case_execution.py`

**Interfaces:**
- Consumes: existing `RunSnapshot`, `Run`, `RunEngine.run`, and `DatasetVersion`.
- Produces: `RunSnapshot.selected_case_ids`, Run lineage fields, and keyword-only selected-Case execution parameters used by `RunManagement`.

- [ ] **Step 1: Write failing snapshot-compatibility and selected-Case tests**

Add a test that reconstructs a pre-selection snapshot hash:

```python
def test_snapshot_accepts_hash_created_before_selected_case_field():
    original = snapshot()
    payload = original.model_dump(
        mode="json", exclude={"snapshot_sha256", "selected_case_ids"}
    )
    serialized = original.model_dump(mode="json")
    serialized.pop("selected_case_ids")
    serialized["snapshot_sha256"] = content_sha256(payload)

    restored = RunSnapshot.model_validate(serialized)

    assert restored.selected_case_ids is None
    assert restored.snapshot_sha256 == serialized["snapshot_sha256"]
```

Create focused execution tests covering one selected Case, empty selection, duplicates, and unknown IDs:

```python
def test_engine_executes_only_selected_case(repository, published_dataset, target):
    selected = published_dataset.cases[0]
    run = RunEngine(repository).run(
        published_dataset,
        target,
        "target-v1",
        selected_case_ids=(selected.id,),
    )
    assert run.snapshot.selected_case_ids == (selected.id,)
    assert {trace.case_id for trace in repository.list_traces(run.id)} == {selected.id}


@pytest.mark.parametrize("selection", [(), ("missing",), ("case-1", "case-1")])
def test_engine_rejects_invalid_case_selection(...):
    with pytest.raises(ValueError):
        RunEngine(repository).run(..., selected_case_ids=selection)
```

- [ ] **Step 2: Run the tests and verify they fail for missing fields/arguments**

Run:

```bash
PYTHONPATH=src python3 -m pytest -q \
  tests/test_snapshot_immutability.py \
  tests/test_selected_case_execution.py
```

Expected: failures showing that `selected_case_ids` and the keyword arguments are not defined.

- [ ] **Step 3: Add the domain fields and hash compatibility**

Add:

```python
class RunSnapshot(DomainModel):
    ...
    selected_case_ids: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def set_or_verify_hash(self) -> "RunSnapshot":
        payload = self.model_dump(mode="json", exclude={"snapshot_sha256"})
        if payload["selected_case_ids"] is None:
            payload.pop("selected_case_ids")
        ...


class Run(DomainModel):
    ...
    parent_run_id: str | None = None
    root_run_id: str | None = None
    rerun_case_id: str | None = None
```

- [ ] **Step 4: Extend RunEngine with validated selection and reusable snapshots/configuration**

Use keyword-only parameters:

```python
def run(
    self,
    dataset: DatasetVersion,
    target: Target,
    target_version: str,
    provider: str = "deterministic",
    evaluators=EVALUATORS,
    *,
    target_snapshot: TargetSnapshot | None = None,
    metric_plan: MetricPlan | None = None,
    gate_spec: GateSpec | None = None,
    selected_case_ids: tuple[str, ...] | None = None,
    parent_run_id: str | None = None,
    root_run_id: str | None = None,
    rerun_case_id: str | None = None,
) -> Run:
```

Validate the selection before creating or saving a Run. Build `cases_to_execute` in Dataset order and persist lineage on the child Run.

- [ ] **Step 5: Run focused and complete backend tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest -q \
  tests/test_snapshot_immutability.py \
  tests/test_selected_case_execution.py
PYTHONPATH=src python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the Run-owned changes**

```bash
git add src/agentgate/domain/run.py src/agentgate/run/core.py \
  tests/test_snapshot_immutability.py tests/test_selected_case_execution.py
git commit -m "feat: support immutable selected-case runs"
```

---

### Task 2: Implement pure Result comparison

**Files:**
- Replace empty boundary: `src/agentgate/result/compare.py`
- Create: `src/agentgate/result/comparison.py`
- Modify: `src/agentgate/result/__init__.py`
- Create: `tests/test_result_comparison.py`

**Interfaces:**
- Consumes: two iterables of domain `Result` objects already filtered to the same Case.
- Produces: `compare_case_results(before, after) -> dict` with `overall`, `counts`, and `evaluators`; no repository or Run dependency.

- [ ] **Step 1: Write the failing Result comparison truth-table tests**

Cover outcome transitions, score transitions, missing Results, ERROR, NOT_APPLICABLE, and overall aggregation:

```python
@pytest.mark.parametrize(("before", "after", "expected"), [
    (("fail", 0.0), ("pass", 1.0), "improved"),
    (("pass", 1.0), ("review", 0.5), "regressed"),
    (("pass", 0.5), ("pass", 0.75), "improved"),
    (("pass", 0.75), ("pass", 0.5), "regressed"),
    (("pass", 1.0), ("pass", 1.0), "unchanged"),
    (("error", None), ("pass", 1.0), "incomparable"),
    (("pass", 1.0), ("not_applicable", None), "incomparable"),
])
def test_result_change_truth_table(before, after, expected): ...
```

Assert the public function pairs by `evaluator_id`, preserves before/after outcome, score, and reason, and returns `mixed` when improvements and regressions coexist.

- [ ] **Step 2: Run the tests and verify the new module/function is missing**

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_result_comparison.py
```

Expected: import failure for `agentgate.result.comparison`.

- [ ] **Step 3: Implement the pure comparison module**

Create these public functions:

```python
def classify_result_change(before: Result | None, after: Result | None) -> str: ...

def summarize_result(result: Result | None) -> dict | None: ...

def compare_case_results(
    before_results: Iterable[Result],
    after_results: Iterable[Result],
) -> dict: ...
```

Keep `result/compare.py` as a temporary import-compatible alias:

```python
from .comparison import compare_case_results

__all__ = ["compare_case_results"]
```

Do not accept repositories, Run IDs, or HTTP types.

- [ ] **Step 4: Run comparison and complete backend tests**

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_result_comparison.py
PYTHONPATH=src python3 -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the Result capability**

```bash
git add src/agentgate/result/compare.py src/agentgate/result/comparison.py \
  src/agentgate/result/__init__.py tests/test_result_comparison.py
git commit -m "feat: add reusable result comparison"
```

---

### Task 3: Add Application-layer rerun commands and queries

**Files:**
- Create: `src/agentgate/application/__init__.py`
- Create: `src/agentgate/application/run_management.py`
- Create: `src/agentgate/application/result_reader.py`
- Create: `src/agentgate/application/target_catalog.py`
- Modify: `src/agentgate/control_plane/service.py`
- Create: `tests/test_single_case_rerun.py`

**Interfaces:**
- Consumes: `AgentGateRepository`, `RunEngine`, `LoanAgent`, and `compare_case_results`.
- Produces: `RunManagement.rerun_case(...) -> Run` and `ResultReader.rerun_comparison(...) -> dict`; `EvaluationService` delegates to these objects.

- [ ] **Step 1: Write failing application tests**

Test:

```python
repository = SQLiteRepository(tmp_path / "rerun.db")
service = EvaluationService(repository)
original = service.launch("loan-agent-v1-risky")
case = original.snapshot.dataset.cases[0]

rerun = service.rerun_case(original.id, case.id, "loan-agent-v2-fixed")

assert rerun.snapshot.dataset == original.snapshot.dataset
assert rerun.snapshot.selected_case_ids == (case.id,)
assert rerun.snapshot.evaluator_specs == original.snapshot.evaluator_specs
assert rerun.snapshot.metric_plan == original.snapshot.metric_plan
assert rerun.snapshot.gate_spec == original.snapshot.gate_spec
assert rerun.parent_run_id == original.id
assert rerun.root_run_id == original.id
assert service.rerun_comparison(rerun.id)["overall"] == "improved"
```

Also test repeated lineage, default latest Target, missing Run/Case/Target, incomplete source Run, normal-Run comparison, and source report immutability.

- [ ] **Step 2: Run the focused tests and verify Application services are missing**

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_single_case_rerun.py
```

Expected: missing rerun methods/Application modules.

- [ ] **Step 3: Implement the Demo `TargetCatalog` boundary**

Provide exact-version validation and explicit latest metadata without relying on tuple or
array order:

```python
class TargetCatalog:
    def versions(self) -> tuple[dict, ...]:
        return (
            {"id": "loan-agent-v1-risky", "label": "风险版本", "is_latest": False},
            {"id": "loan-agent-v2-fixed", "label": "修复版本", "is_latest": True},
        )

    def resolve(self, version: str | None) -> str:
        selected = version or next(item["id"] for item in self.versions() if item["is_latest"])
        if selected not in {item["id"] for item in self.versions()}:
            raise ValueError(f"unknown target version: {selected}")
        return selected
```

The POC implementation is Demo-backed, but callers depend only on this catalog boundary.

- [ ] **Step 4: Implement `RunManagement`**

Provide:

```python
class RunManagement:
    def __init__(
        self,
        repository: AgentGateRepository,
        engine: RunEngine,
        target_catalog: TargetCatalog,
    ) -> None: ...

    def latest_target_version(self) -> str: ...

    def rerun_case(
        self,
        source_run_id: str,
        case_id: str,
        target_version: str | None = None,
    ) -> Run: ...
```

Resolve the Case only from `source.snapshot.dataset`, validate before calling the engine,
and pass the original Dataset, Evaluators, MetricPlan, GateSpec, direct parent, root, and
Case ID explicitly.

- [ ] **Step 5: Implement `ResultReader`**

Provide:

```python
class ResultReader:
    def __init__(self, repository: AgentGateRepository, engine: RunEngine) -> None: ...

    def run_detail(self, run_id: str): ...

    def trace(self, run_id: str, case_id: str): ...

    def rerun_comparison(self, rerun_run_id: str) -> dict: ...
```

The query validates rerun lineage, loads parent/child Results for the Case, delegates to
`compare_case_results`, and adds Run IDs, Case metadata, and Target versions.

- [ ] **Step 6: Convert `EvaluationService` to delegation**

Construct the catalog and two Application services in `EvaluationService.__init__`; keep
public methods as thin forwarding methods. `versions()` delegates to the catalog. Remove
`_result_summary`, `_comparison_status`, and `_overall_comparison` from
`control_plane/service.py`.

- [ ] **Step 7: Run focused, architecture-boundary, and complete backend tests**

```bash
PYTHONPATH=src python3 -m pytest -q \
  tests/test_single_case_rerun.py \
  tests/test_result_comparison.py
PYTHONPATH=src python3 -m pytest -q
```

Additionally verify no comparison algorithm remains in the compatibility facade:

```bash
rg -n "def (_comparison_status|_overall_comparison)" src/agentgate/control_plane
```

Expected: no matches and all tests pass.

- [ ] **Step 8: Commit the Application-layer migration**

```bash
git add src/agentgate/application src/agentgate/control_plane/service.py \
  tests/test_single_case_rerun.py
git commit -m "refactor: move rerun workflow into application layer"
```

---

### Task 4: Restore API compatibility and explicit latest Target metadata

**Files:**
- Modify: `src/agentgate/server/application.py`
- Create: `tests/test_single_case_rerun_api.py`

**Interfaces:**
- Consumes: delegation methods on `EvaluationService`.
- Produces: stable rerun/comparison HTTP endpoints and `is_latest` version metadata.

- [ ] **Step 1: Write failing API tests**

Cover successful creation/comparison and status mappings:

```python
response = client.post(
    f"/api/runs/{run_id}/cases/{case_id}/rerun",
    json={"target_version": "loan-agent-v2-fixed"},
)
assert response.status_code == 201
rerun = response.json()
assert rerun["snapshot"]["selected_case_ids"] == [case_id]
assert client.get(f"/api/runs/{rerun['id']}/comparison").status_code == 200
```

Assert missing Run/Case maps to 404; invalid state/version/normal comparison maps to 422;
and exactly one `/api/versions` entry has `is_latest=true`.

- [ ] **Step 2: Run the API tests and verify endpoint failures**

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_single_case_rerun_api.py
```

- [ ] **Step 3: Implement request model and routes**

Add `RerunCaseRequest`, the POST route, and the comparison GET route. Convert
`LookupError` to 404 and `ValueError` to 422 without creating partial Runs.

Add explicit latest metadata in the versions response:

```python
{
    "id": version,
    "label": ...,
    "is_latest": version == self.run_management.latest_target_version(),
}
```

- [ ] **Step 4: Run API and full backend tests**

```bash
PYTHONPATH=src python3 -m pytest -q tests/test_single_case_rerun_api.py
PYTHONPATH=src python3 -m pytest -q
```

- [ ] **Step 5: Commit API compatibility**

```bash
git add src/agentgate/server/application.py tests/test_single_case_rerun_api.py
git commit -m "feat: expose single-case rerun API"
```

---

### Task 5: Restore the verified Web workflow

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/src/App.vue`
- Modify: `web/src/style.css`
- Modify: `web/tests/demo.spec.ts`
- Modify if necessary for stable existing selectors: `web/tests/dataset.spec.ts`

**Interfaces:**
- Consumes: stable rerun/comparison API and `Version.is_latest`.
- Produces: one rerun action per Case, Target-version selection, and comparison display.

- [ ] **Step 1: Add the failing browser scenario**

Add a Playwright test that launches the risky version, asserts one rerun button for the
Case, confirms the latest fixed version is selected, submits the rerun, and observes an
improved comparison.

```typescript
await expect(page.getByRole('button', { name: '重新运行此Case' })).toHaveCount(1)
await expect(page.getByTestId('rerun-version-select')).toContainText('loan-agent-v2-fixed')
await page.getByTestId('submit-rerun').click()
await expect(page.getByTestId('rerun-comparison')).toContainText('改善')
```

- [ ] **Step 2: Run the browser test and verify the workflow is absent**

```bash
cd web
npm run test:e2e -- --grep "reruns one Case"
```

- [ ] **Step 3: Add client types and methods**

Add Run lineage/selection fields, `RerunComparison`, `rerunCase`, and `comparison`. Make
`Version.is_latest` required.

- [ ] **Step 4: Implement Case-grouped results and rerun interaction**

Group evaluator Results by Case, expose one action per Case, default the selector from
`is_latest`, disable duplicate submissions, retain the original report, show comparison
counts/details beneath it, and allow opening the child report.

- [ ] **Step 5: Run frontend verification**

```bash
cd web
npm run typecheck
npm run build
npm run test:e2e
```

Expected: typecheck, production build, and all browser tests pass.

- [ ] **Step 6: Commit the Web workflow**

```bash
git add web/src/api/client.ts web/src/App.vue web/src/style.css \
  web/tests/demo.spec.ts web/tests/dataset.spec.ts
git commit -m "feat: restore single-case rerun web workflow"
```

---

### Task 6: Final compatibility and documentation verification

**Files:**
- Modify: `docs/run/README.md`
- Modify: `docs/result/README.md`

**Interfaces:**
- Consumes: all completed backend and frontend work.
- Produces: verified progress evidence and architecture-aligned documentation.

- [ ] **Step 1: Run final verification from a clean worktree**

```bash
git status --short
PYTHONPATH=src python3 -m pytest -q
cd web
npm run typecheck
npm run build
npm run test:e2e
```

Expected: only intended documentation edits are uncommitted before the final commit; all
test commands pass.

- [ ] **Step 2: Inspect architecture boundaries**

```bash
rg -n "rerun|comparison" src/agentgate/application src/agentgate/result \
  src/agentgate/control_plane src/agentgate/run src/agentgate/server
git diff --check
```

Confirm that comparison is pure, Application owns orchestration, Control Plane delegates,
and Server only maps transport concerns.

- [ ] **Step 3: Update verified documentation**

Record Single-Case rerun as implemented only after the commands above pass. Link the Run
README to the design and plan, and document the reusable comparison capability in the
Result README. Do not edit the archived P1 progress file or restore superseded module
ownership in the pre-refactor Dataset record.

- [ ] **Step 4: Commit verified documentation**

```bash
git add docs/run/README.md docs/result/README.md
git commit -m "docs: record refactored single-case rerun"
```

- [ ] **Step 5: Review the final branch diff**

```bash
git status --short
git log --oneline devfork/review/refactor-1-architecture..HEAD
git diff --stat devfork/review/refactor-1-architecture...HEAD
git diff --check devfork/review/refactor-1-architecture...HEAD
```

Expected: clean worktree; only Single-Case rerun, its architecture migration, tests, and
documentation are present.
