# Dataset Excel Final Fix Report

## Status

All six final-review findings are implemented and verified on `codex/local-development`.
The existing transaction-based all-or-nothing persistence behavior remains in place.

## Finding 1: Full DatasetVersion validation before persistence

### Fix

- `DatasetService.import_excel()` now constructs the Draft and runs
  `validate_dataset_version()` before entering the repository transaction.
- `DatasetValidationError` paths are mapped back to the originating `Cases` worksheet row and
  column, then re-raised as `DatasetExcelValidationError` for the existing structured HTTP 422
  response.
- The mapping covers workbook-level, Case-level, Turn-level, and nested Expectation paths. A
  cross-Turn duplicate Expectation ID test proves that Turn index 1 maps to Excel row 3.
- Empty workbooks, empty Turn input, required/forbidden tool overlap, duplicate Expectation IDs,
  and unsupported JSON Schema conditions are rejected before either Dataset table changes.

### Files

- `src/agentgate/case/service.py`
- `src/agentgate/case/excel_import_export.py`
- `tests/test_dataset_excel_import_export.py`
- `tests/test_dataset_excel_api.py`

### RED / GREEN evidence

- RED: five focused service tests failed with `DID NOT RAISE
  DatasetExcelValidationError`; two API tests returned 201 instead of 422.
- GREEN: the same focused service tests passed 5/5 and API tests passed 2/2. Each persistence
  assertion checks that Dataset and DatasetVersion counts are unchanged from the pre-request
  baseline.

## Finding 2: Formula-safe, lossless round-trip

### Fix

- Export uses `WriteOnlyCell` with explicit string data type for every text cell. Formula-like
  values such as `=1+1` and `=HYPERLINK(...)` remain literal text without an apostrophe prefix.
- Import opens with `data_only=False`, examines every header/data cell's type, rejects formulas in
  every column, and never trusts cached formula results.

### Files

- `src/agentgate/case/excel_import_export.py`
- `tests/test_dataset_excel_import_export.py`
- `tests/test_dataset_excel_api.py`
- `README.md`

### RED / GREEN evidence

- RED: formula-like export cells had `data_type == "f"`; upload formulas were reported as blank
  values; the focused codec group had four expected failures.
- GREEN: formula-like IDs, names, notes, Turn IDs, and expected skills are type `s`, retain their
  exact values, and round-trip. Formula upload returns a structured 422 at `Cases!input_json row 2`.

## Finding 3: Excel cell representability

### Fix

- Export validates all rendered cell values before creating the workbook.
- Text is limited to 32,767 characters and checked against the XML 1.0 legal character ranges.
- `DatasetExcelExportError` and `ExcelExportIssue` carry structured sheet/row/column errors.
- The Excel export endpoint maps representability errors to 422 while unknown Dataset versions
  continue to return 404.

### Files

- `src/agentgate/case/excel_import_export.py`
- `src/agentgate/case/__init__.py`
- `src/agentgate/server/application.py`
- `tests/test_dataset_excel_import_export.py`
- `tests/test_dataset_excel_api.py`
- `README.md`

### RED / GREEN evidence

- RED: 32,768 characters were silently truncated and an XML control character raised
  openpyxl `IllegalCharacterError`; the API returned 200 for the oversized cell.
- GREEN: 32,767 characters round-trip exactly; 32,768 and `U+0001` produce structured export
  errors; the API returns structured 422.

## Finding 4: Malformed OOXML package normalization

### Fix

- ZIP and openpyxl load/lazy-iteration boundaries normalize known package exceptions, including
  `KeyError`, `BadZipFile`, XML `ParseError`, and `InvalidFileException`.
- An empty ZIP or package missing `[Content_Types].xml` returns a structured 422.
- The previous broad `ValueError` catch was removed. A focused test injects an application
  parsing `ValueError` and proves it is not mislabeled as corrupt XLSX content.

### Files

- `src/agentgate/case/excel_import_export.py`
- `tests/test_dataset_excel_import_export.py`
- `tests/test_dataset_excel_api.py`

### RED / GREEN evidence

- RED: empty/missing-part packages returned 500 and application `ValueError` was wrapped as an
  Excel validation error.
- GREEN: both malformed package API cases return structured 422, lazy XML corruption remains
  normalized, and application errors propagate unchanged.

## Finding 5: Request, file, archive, and event-loop boundaries

### Fix

- A route-scoped ASGI middleware rejects a declared or streamed multipart body above 11 MiB
  before FastAPI multipart parsing. It buffers and replays only accepted request bodies.
- The file payload remains limited to exactly 10 MiB and is still read at most one byte beyond
  that limit. A valid padded XLSX at exactly 10 MiB imports successfully.
- ZIP central-directory metadata is checked before openpyxl: 100 MiB total uncompressed size,
  50 MiB per entry, and 200:1 maximum compression ratio.
- `DatasetService.import_excel()` now runs through Starlette's threadpool from the async endpoint,
  moving openpyxl parsing, validation, and synchronous persistence off the event loop.

### Files

- `src/agentgate/case/excel_import_export.py`
- `src/agentgate/server/application.py`
- `tests/test_dataset_excel_import_export.py`
- `tests/test_dataset_excel_api.py`
- `README.md`
- `web/README.md`

### RED / GREEN evidence

- RED: oversized Content-Length and streamed requests reached multipart parsing and returned 400;
  service import observed a running event loop; compression bombs reached openpyxl.
- GREEN: six focused API boundary tests passed together, three archive-limit codec tests passed,
  and the exact-10-MiB characterization test passed.

## Finding 6: Verified project progress

### Fix

- `docs/progress.md` marks JSON plus Excel Dataset import/export as implemented and verified.
- Automatic Case/template generation and single-Case rerun remain explicitly deferred.
- The verified Python and Playwright counts were refreshed without changing unrelated module
  status claims.

### Files

- `docs/progress.md`

## Final verification

- Baseline before final fixes:
  `pytest -q tests/test_dataset_excel_import_export.py tests/test_dataset_excel_api.py` — 24 passed.
- Focused final:
  `pytest -q tests/test_dataset_excel_import_export.py tests/test_dataset_excel_api.py` — 49 passed.
- Python full:
  `pytest -q` — 96 passed.
- Web typecheck:
  `npm run typecheck` — passed.
- Web production build:
  `npm run build` — passed; Vite retained its pre-existing >500 kB chunk warning.
- Web full Playwright:
  `npm run test:e2e` — 14 passed across desktop and mobile projects.
- Whitespace/diff validation:
  `git diff --check` — passed.

## Self-review

- Re-read the authoritative specification and all six controller findings against the final diff.
- Confirmed validation occurs before the transaction and all invalid-import tests assert unchanged
  Dataset and DatasetVersion persistence counts.
- Confirmed every exported string cell is forced to text and no apostrophe mutates source values.
- Confirmed export errors take the 422 branch before the endpoint's unknown-version 404 handler.
- Confirmed only ZIP/openpyxl boundaries catch package exceptions; application parsing and domain
  errors are not hidden.
- Confirmed Content-Length and streamed-body paths share the same structured request-limit error,
  while exact 10 MiB file acceptance and 10 MiB + 1 rejection are both tested.
- Confirmed archive limits are documented as conservative and tunable.
- Confirmed no schema, evaluator, RunEngine, trace, result, or canonical JSON endpoint changes.
- No sub-agents were used.

## Concerns

- The conservative 200:1 ZIP ratio can reject an unusually compressible but legitimate workbook;
  this is intentional, documented, and isolated behind constants for future tuning.
- Web verification emits existing Vite chunk-size, `NO_COLOR`, and transient ResizeObserver
  warnings, but typecheck, build, and all 14 Playwright tests complete successfully.
