# AgentGate Web

Chinese P1 evaluation UI backed by the AgentGate REST API.

Stack:

- Vue 3
- TypeScript
- Vite
- Element Plus

The Web UI should call the AgentGate REST API. It should not import Python backend code directly.

Run `npm install`, then start FastAPI on port 8000 and run `npm run dev`. Use `npm run build` for a production build and `npm run test:e2e` for desktop/mobile checks.

## Dataset Excel workflow

In the Dataset workspace, select **Import Excel**, choose an `.xlsx` workbook, and enter the
Dataset name (with an optional description). The dialog sends the workbook as multipart form data
to `POST /api/datasets/import/excel`; the name and description are entered in the dialog, not in
the workbook.

The import creates a new Dataset and a Draft version. If the workbook is invalid, no Dataset is
created and the dialog displays the returned worksheet, row, column, and error message. After a
successful import, review or edit the Draft, validate it, and select **Publish** manually. Only a
published version can be downloaded with **Export Excel**, which calls
`GET /api/datasets/{dataset_id}/versions/{version}/export/excel`.

Excel workbooks require a `Cases` sheet and use one data row per Turn. Multi-turn rows share a
`case_id` and have contiguous 1-based `turn_order` values. They are limited to 10 MiB and 10,000
data rows. See the root [`README.md`](../README.md#dataset-excel-import-and-export) for the exact
column schema, JSON-cell examples, and API curl commands.
