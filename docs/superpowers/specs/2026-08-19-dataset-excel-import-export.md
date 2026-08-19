# Dataset Excel Import/Export Specification

## Scope

Add Excel import, Excel export, and Web operations to Dataset & Case management while preserving all existing canonical JSON behavior. No evaluator, RunEngine, trace, result, or storage-schema changes are in scope.

## Workbook contract

- File format: `.xlsx`.
- Worksheet name: `Cases`.
- One row represents one `CaseTurn`.
- Rows sharing `case_id` are merged into one multi-turn `Case` and ordered by `turn_order`.
- Required columns: `case_id`, `case_name`, `turn_id`, `turn_order`, `input_json`, `expectations_json`.
- Optional columns: `case_description`, `category`, `difficulty`, `tags_json`, `initial_state_json`, `expected_skill`, `required_tools_json`, `forbidden_tools_json`, `policy_rules_json`, `turn_notes`.
- `case_description` maps to the existing `Case.notes` field; no domain-model field is added.
- `category` defaults to `positive`; `difficulty` defaults to `medium`.
- Blank optional JSON cells use their domain defaults: `{}` for `initial_state_json`, and `[]` for list/tuple fields.
- All JSON cells contain canonical JSON text, not comma-separated values.
- Case-level values repeated across rows with the same `case_id` must agree. A mismatch is a validation error.
- Case, Turn, and Expectation IDs are preserved on export and import.

## Import behavior

- The Web dialog collects Dataset name and description separately from the workbook.
- A successful import creates a new Dataset with a newly generated Dataset ID and one Draft DatasetVersion.
- The imported Draft must be reviewed and manually published through the existing workflow.
- Import is all-or-nothing: parse and validate the entire workbook before saving either object.
- All independently discoverable errors are returned together.
- Each error identifies worksheet, 1-based row, column, and message.
- Duplicate Turn IDs, duplicate or non-contiguous `turn_order`, invalid JSON, invalid enum values, invalid domain objects, missing headers, blank required cells, inconsistent Case-level values, and normal DatasetVersion validation failures are rejected.
- Existing JSON import remains unchanged.

## Export behavior

- Only published Dataset versions may be exported.
- The generated workbook uses the import contract above and can be imported as a new Dataset Draft.
- Rows follow Dataset case order and each Case's turn order.
- Dataset metadata is not embedded in the workbook.
- Existing JSON export remains unchanged.

## HTTP and Web behavior

- `POST /api/datasets/import/excel` accepts multipart fields `file`, `name`, and optional `description`; success returns `{dataset, version}` with HTTP 201.
- Invalid workbooks return HTTP 422 with structured issue objects.
- `GET /api/datasets/{dataset_id}/versions/{version}/export/excel` returns an XLSX attachment and rejects drafts or unknown versions.
- Dataset Workspace keeps the JSON import control, adds a separate Excel import dialog, displays all structured Excel errors, and adds Excel export for published versions.

## Dependencies and constraints

- Python is `>=3.11`.
- Use `openpyxl` for XLSX reading/writing and `python-multipart` for FastAPI multipart parsing.
- Parsing limits: one workbook, one `Cases` sheet, at most 10,000 data rows, and at most 10 MiB uploaded bytes.
- Do not add database tables or migrations.
- Do not change canonical JSON payloads or endpoints.

