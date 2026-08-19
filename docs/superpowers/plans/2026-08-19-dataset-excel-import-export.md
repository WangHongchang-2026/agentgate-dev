# Dataset Excel Import/Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lossless XLSX import/export and Dataset Workspace controls while preserving the current JSON workflow.

**Architecture:** A focused `excel_import_export.py` adapter translates between XLSX bytes and existing `Case` objects. `DatasetService` owns the atomic create-Dataset-and-Draft transaction boundary, FastAPI exposes multipart/download endpoints, and the Vue workspace provides explicit JSON and Excel actions.

**Tech Stack:** Python 3.11, Pydantic 2, openpyxl, FastAPI multipart/StreamingResponse, Vue 3, TypeScript, Element Plus, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-19-dataset-excel-import-export.md`

## Global Constraints

- Preserve existing JSON import/export payloads, endpoints, and behavior.
- Excel import always creates a new Dataset ID and a Draft; users publish manually.
- Preserve Case, Turn, and Expectation IDs.
- Reject the entire workbook and save nothing if any error exists.
- Export published versions only.
- Accept at most 10,000 rows and 10 MiB per workbook.
- Do not change database schema, evaluators, RunEngine, trace, or result code.

---

### Task 1: XLSX codec and structured validation

**Files:**
- Create: `src/agentgate/case/excel_import_export.py`
- Modify: `src/agentgate/case/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/test_dataset_excel_import_export.py`

**Interfaces:**
- Produces: `ExcelImportIssue(sheet: str, row: int | None, column: str | None, message: str)`.
- Produces: `DatasetExcelValidationError(ValueError)` with `issues: tuple[ExcelImportIssue, ...]`.
- Produces: `parse_excel(content: bytes) -> tuple[Case, ...]`.
- Produces: `build_excel(version: DatasetVersion) -> bytes`.
- Consumes: existing `Case`, `CaseTurn`, `DatasetVersion`, and discriminated `Expectation` models.

- [ ] **Step 1: Add failing codec tests**

  Test a two-turn Case containing all Case/Turn fields and three expectation kinds. Assert `parse_excel(build_excel(version)) == version.cases`, IDs are unchanged, row order is stable, the sheet is `Cases`, and headers match the specification.

  ```python
  def test_excel_round_trip_preserves_multiturn_case_and_ids():
      content = build_excel(published_version_with_all_fields())
      parsed = parse_excel(content)
      assert parsed == published_version_with_all_fields().cases
  ```

- [ ] **Step 2: Verify the codec test fails**

  Run: `pytest tests/test_dataset_excel_import_export.py::test_excel_round_trip_preserves_multiturn_case_and_ids -v`

  Expected: FAIL because `agentgate.case.excel_import_export` does not exist.

- [ ] **Step 3: Add dependencies and the minimal exporter**

  Add runtime dependencies `openpyxl>=3.1,<4` and `python-multipart>=0.0.9`. Implement `build_excel()` with a write-only in-memory workbook, the exact ordered headers from the spec, compact JSON via `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`, and deterministic Case/Turn row order.

- [ ] **Step 4: Implement the parser and issue aggregation**

  Read only the `Cases` sheet in read-only/data-only mode. Check file/sheet/header/row limits, parse every JSON cell independently, group rows by `case_id`, verify repeated Case fields, validate `turn_order`, then build models with `Case.model_validate`. Convert `JSONDecodeError`, `ValidationError`, and structural checks into `ExcelImportIssue` records. Raise one `DatasetExcelValidationError(tuple(issues))` after scanning all rows.

- [ ] **Step 5: Add failing malformed-workbook tests**

  Cover missing sheet/header, blank required cell, malformed JSON in multiple rows, repeated Case-field conflicts, duplicate Turn IDs, duplicate/non-contiguous turn orders, invalid category/difficulty, invalid Expectation objects, row limit, and invalid XLSX bytes. Assert errors contain sheet, row, column, and message, and multiple independent errors are returned together.

- [ ] **Step 6: Run codec tests and fix only codec behavior**

  Run: `pytest tests/test_dataset_excel_import_export.py -v`

  Expected: PASS.

- [ ] **Step 7: Run existing JSON regression test**

  Run: `pytest tests/test_dataset_import_export.py -v`

  Expected: PASS with no JSON behavior change.

- [ ] **Step 8: Commit the codec**

  ```bash
  git add pyproject.toml src/agentgate/case/__init__.py src/agentgate/case/excel_import_export.py tests/test_dataset_excel_import_export.py
  git commit -m "feat: add dataset Excel codec"
  ```

### Task 2: Atomic Dataset service workflow

**Files:**
- Modify: `src/agentgate/case/service.py`
- Modify: `tests/test_dataset_excel_import_export.py`

**Interfaces:**
- Consumes: `parse_excel(content: bytes)` and `build_excel(version)` from Task 1.
- Produces: `DatasetService.import_excel(content: bytes, name: str, description: str = "") -> tuple[Dataset, DatasetVersion]`.
- Produces: `DatasetService.export_excel(dataset_id: str, version: int) -> bytes`.

- [ ] **Step 1: Add failing service tests**

  Assert a valid workbook creates a new Dataset plus Draft, trims name/description, preserves nested IDs, sets `version is None`, and requires manual publishing. Assert blank name fails. Assert malformed Excel leaves dataset/version counts unchanged. Assert export rejects a Draft and round-trips a published version.

- [ ] **Step 2: Verify service tests fail**

  Run: `pytest tests/test_dataset_excel_import_export.py -k 'service' -v`

  Expected: FAIL because service methods do not exist.

- [ ] **Step 3: Implement import after validation**

  Parse all bytes and construct a `DatasetVersion` before calling either repository save. Use `create_dataset()` only after parsing and validation succeed, then save exactly one Draft with the parsed cases. If repository persistence can fail between the two existing saves, add a repository transaction context only around these saves; do not alter schema.

- [ ] **Step 4: Implement published-only export**

  Fetch the requested version, require `status == DatasetVersionStatus.PUBLISHED`, and pass it to `build_excel()`.

- [ ] **Step 5: Run service and repository regressions**

  Run: `pytest tests/test_dataset_excel_import_export.py tests/test_dataset_service.py tests/test_dataset_repository.py -v`

  Expected: PASS.

- [ ] **Step 6: Commit the service workflow**

  ```bash
  git add src/agentgate/case/service.py tests/test_dataset_excel_import_export.py
  git commit -m "feat: add atomic Excel dataset workflow"
  ```

### Task 3: FastAPI import and download endpoints

**Files:**
- Modify: `src/agentgate/server/application.py`
- Create: `tests/test_dataset_excel_api.py`

**Interfaces:**
- Consumes: Task 2 service methods and Task 1 structured errors.
- Produces: `POST /api/datasets/import/excel` multipart endpoint.
- Produces: `GET /api/datasets/{dataset_id}/versions/{version}/export/excel` attachment endpoint.

- [ ] **Step 1: Add failing API happy-path test**

  Upload a generated workbook with multipart `file`, `name`, and `description`. Assert HTTP 201, a new Dataset ID, Draft status, preserved Case/Turn IDs, and subsequent Dataset detail visibility. Publish it, download XLSX, and assert MIME type and `Content-Disposition` attachment filename.

- [ ] **Step 2: Verify happy-path API test fails**

  Run: `pytest tests/test_dataset_excel_api.py::test_excel_import_creates_draft_and_published_export_downloads -v`

  Expected: FAIL with HTTP 404.

- [ ] **Step 3: Implement multipart import and streaming export**

  Use `UploadFile`, `File`, and `Form`; reject non-`.xlsx` filenames and bodies over 10 MiB. Return `StreamingResponse(BytesIO(content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")` with a sanitized attachment filename.

- [ ] **Step 4: Map structured validation errors**

  Extend `_raise_dataset_error` so `DatasetExcelValidationError.issues` serialize as `{sheet,row,column,message}`. Keep existing `DatasetValidationError` serialization unchanged.

- [ ] **Step 5: Add and run API failure tests**

  Test missing name, wrong extension, oversized upload, malformed workbook returning multiple issues, unknown version, and attempted Draft export. Assert failed imports do not create a Dataset.

  Run: `pytest tests/test_dataset_excel_api.py tests/test_dataset_api.py tests/test_dataset_import_export.py -v`

  Expected: PASS.

- [ ] **Step 6: Commit API endpoints**

  ```bash
  git add src/agentgate/server/application.py tests/test_dataset_excel_api.py
  git commit -m "feat: expose dataset Excel APIs"
  ```

### Task 4: Web API client and file downloads

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/datasets.ts`
- Modify: `web/src/types/dataset.ts`
- Modify: `web/src/pages/DatasetWorkspace.vue`
- Modify: `web/tests/dataset.spec.ts`

**Interfaces:**
- Produces: `ExcelImportIssue` TypeScript type.
- Produces: `datasetApi.importExcel(file, name, description)` using `FormData` without a manual Content-Type header.
- Produces: `datasetApi.exportExcel(datasetId, version) -> Promise<Blob>`.

- [ ] **Step 1: Add failing Playwright import test**

  Generate or commit no binary fixture: obtain a workbook through the real export endpoint during test setup, then use `setInputFiles`. Assert the Excel dialog requires a name, imports to a selected Draft, retains the Case, and allows normal manual publication.

- [ ] **Step 2: Add failing Playwright error-display test**

  Upload invalid XLSX bytes and assert the dialog shows the structured sheet/row/column error without closing or creating a Dataset.

- [ ] **Step 3: Add binary response support to the API client**

  Add a small `requestBlob(url, init?)` helper that shares `ApiError` handling but returns `response.blob()`. Keep the existing JSON `request()` contract unchanged.

- [ ] **Step 4: Implement explicit Excel import UI**

  Keep the current hidden JSON input and handler. Add an “导入 Excel” action, a dialog with name, description, `.xlsx` file selection, loading state, and a structured issue list. On success close the dialog, reload/select the newly created Dataset Draft, and show `Excel 已导入为草稿`.

- [ ] **Step 5: Implement Excel export UI**

  Add an Excel export action next to JSON export for published versions. Use the returned Blob, a temporary object URL, a sanitized `${datasetName}-v${version}.xlsx` filename, click the link, and revoke the URL.

- [ ] **Step 6: Run TypeScript checks**

  Run: `npm run typecheck && npm run build`

  Workdir: `web`

  Expected: both commands succeed.

- [ ] **Step 7: Run Dataset browser tests**

  Run: `npm run test:e2e -- tests/dataset.spec.ts`

  Workdir: `web`

  Expected: PASS including existing Dataset workflow.

- [ ] **Step 8: Commit Web operations**

  ```bash
  git add web/src/api/client.ts web/src/api/datasets.ts web/src/types/dataset.ts web/src/pages/DatasetWorkspace.vue web/tests/dataset.spec.ts
  git commit -m "feat: add dataset Excel web workflow"
  ```

### Task 5: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `web/README.md`

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: user-facing workbook schema, curl examples, and Web workflow documentation.

- [ ] **Step 1: Document the workbook and API**

  Add the exact column table, a two-row multi-turn example, JSON-cell examples, import-as-Draft semantics, all-or-nothing errors, published-only export, the 10 MiB/10,000-row limits, and multipart/download curl commands.

- [ ] **Step 2: Run Python verification**

  Run: `pytest -q`

  Expected: all tests pass.

- [ ] **Step 3: Run Web verification**

  Run: `npm run typecheck && npm run build && npm run test:e2e`

  Workdir: `web`

  Expected: all commands pass.

- [ ] **Step 4: Verify the worktree diff is scoped**

  Run: `git status --short && git diff --check`

  Expected: only planned files are modified and `git diff --check` emits no errors.

- [ ] **Step 5: Commit documentation**

  ```bash
  git add README.md web/README.md
  git commit -m "docs: describe dataset Excel workflow"
  ```

