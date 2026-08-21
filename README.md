# AgentGate

AgentGate is an open-source evaluation harness for enterprise agents.

It helps teams run agent test cases, collect traces, evaluate behavior, compare versions, and make release gate decisions.

## Goal

AgentGate focuses on:

- Active evaluation: run cases against an agent.
- Passive evaluation: score existing production traces.
- Business contracts: validate tool calls, arguments, policies, workflow rules, and final state.
- Release gates: decide whether an agent/model/prompt version is safe to ship.
- Dataset growth: turn failures and traces into regression cases.

## Initial Architecture

```text
CLI / Web / REST API
        |
    Control Layer
        |
Case -> Run -> Trace -> Evaluator -> Result
```

## Project Layout

```text
src/agentgate/
  case/          # Cases, datasets, custom/public benchmark import
  run/           # Run engine, targets, lifecycle
  trace/         # Trace model, OTel import, execution graph
  evaluator/     # Built-in and external evaluators
  result/        # Results, reports, compare, release gates
  experiment/    # Controlled A/B experiments and statistical decisions
  queue/         # Public reservation and queue orchestration
  optimizer/     # Badcase analysis and human-reviewed recommendations
  lineage/       # Asset versions and dependency lineage
  control_plane/ # Local control-plane service used by CLI/API/Web
  cli/           # Command-line entry point
  server/        # REST API entry point

web/             # Vue/TypeScript evaluation UI
docs/            # Design docs
examples/        # Demo agents and datasets
tests/           # Test suite
```

The five core evaluation objects remain `Case -> Run + Trace -> Evaluator -> Result`.
Experiment, queue, optimizer, and lineage are product modules composed around that core;
they do not replace it. See `docs/capability-mapping.md` for capability ownership and
implementation status.

## First Demo Target

The first demo should be a loan approval agent:

- The agent may create a loan application.
- The agent must not approve high-risk loans directly.
- Approval may require human review.
- Evaluators check tool calls, tool arguments, workflow policy, and final state.

## P1 Demo

The repository contains a working SQLite-backed loan-approval evaluation slice with a deterministic target, CLI, REST/OTLP HTTP endpoints, and Chinese Vue UI. See `docs/progress.md` for verified implementation status and `docs/demo-test-guide.md` for the complete setup and test walkthrough.

## Dataset Excel import and export

Datasets can be exchanged as Excel workbooks for authoring and review. Excel import creates a
new Dataset with a Draft version; it does not modify an existing Dataset. Publish that Draft in
the Dataset workspace before it can be used for evaluation or exported. The existing JSON import
and export workflow is unchanged.

### Workbook format

Upload an `.xlsx` workbook with a required worksheet named `Cases`. Its first row
must contain these columns, in this exact order; each following row represents one conversation
Turn. Rows sharing a `case_id` form one multi-turn Case, whose `turn_order` values must be
1-based and contiguous.

| # | Column | Required | Meaning |
| --- | --- | --- | --- |
| 1 | `case_id` | Yes | Stable Case ID; repeated for every Turn in the Case. |
| 2 | `case_name` | Yes | Case display name; must be the same on every row for that Case. |
| 3 | `case_description` | No | Case notes/description; defaults to an empty string. |
| 4 | `category` | No | `positive`, `negative`, or `boundary`; defaults to `positive`. |
| 5 | `difficulty` | No | `easy`, `medium`, or `hard`; defaults to `medium`. |
| 6 | `tags_json` | No | JSON array of Case tag strings; defaults to `[]`. |
| 7 | `initial_state_json` | No | JSON object containing the Case's initial state; defaults to `{}`. |
| 8 | `turn_id` | Yes | Stable Turn ID, unique within its Case. |
| 9 | `turn_order` | Yes | Integer ordering the Turns within the Case, starting at 1 with no gaps. |
| 10 | `input_json` | Yes | JSON object supplied to the agent for this Turn. |
| 11 | `expected_skill` | No | Optional expected skill name. |
| 12 | `expectations_json` | Yes | JSON array of expectation objects; use `[]` when none are needed. |
| 13 | `required_tools_json` | No | JSON array of tool names that must be called; defaults to `[]`. |
| 14 | `forbidden_tools_json` | No | JSON array of tool names that must not be called; defaults to `[]`. |
| 15 | `policy_rules_json` | No | JSON array of policy-rule strings; defaults to `[]`. |
| 16 | `turn_notes` | No | Per-Turn notes; defaults to an empty string. |

All `*_json` cells contain JSON text, not spreadsheet formulas or native cell objects. Formula
cells are rejected in every column rather than evaluated or read from cached results. On export,
text that begins with `=` (for example, a Case ID or note) is written as literal text, so it does
not become a formula and round-trips without adding an apostrophe. For
example, `tags_json` can be `["loan","multi-turn"]`, `initial_state_json` can be
`{"customer_id":"c-17","risk":"unknown"}`, and `input_json` can be
`{"message":"I want to apply for a loan"}`. An `expectations_json` cell can contain:

```json
[
  {
    "id": "expect-output-1",
    "kind": "output",
    "path": null,
    "condition": {"kind": "matches_pattern", "pattern": "(?i)application"},
    "name": "Mentions the application"
  }
]
```

Here is a two-row, multi-turn example. The Case-level values are intentionally repeated on both
rows; they must agree for a shared `case_id`.

| case_id | case_name | case_description | category | difficulty | tags_json | initial_state_json | turn_id | turn_order | input_json | expected_skill | expectations_json | required_tools_json | forbidden_tools_json | policy_rules_json | turn_notes |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- |
| `loan-1` | `Loan application` | `Collect application details` | `positive` | `medium` | `["loan","multi-turn"]` | `{"customer_id":"c-17"}` | `loan-1-turn-1` | 1 | `{"message":"I want to apply"}` | `collect_application` | `[]` | `["lookup_customer"]` | `[]` | `["collect applicant consent"]` | `Ask for consent.` |
| `loan-1` | `Loan application` | `Collect application details` | `positive` | `medium` | `["loan","multi-turn"]` | `{"customer_id":"c-17"}` | `loan-1-turn-2` | 2 | `{"message":"I consent. My income is 90000."}` | `submit_application` | `[{"id":"expect-output-2","kind":"output","condition":{"kind":"matches_pattern","pattern":"(?i)submitted"}}]` | `["create_application"]` | `["approve_loan"]` | `["do not approve directly"]` | `Submit only.` |

The import is all-or-nothing. A malformed workbook, missing required values, invalid JSON,
conflicting repeated Case values, duplicate IDs/orders, or non-contiguous `turn_order` values
creates no Dataset. Validation responses identify each issue with `sheet`, `row`, `column`, and
`message`. Each text cell is limited to 32,767 characters and must contain only XML 1.0 legal
characters; an export that cannot represent a cell losslessly returns a structured validation
error instead of truncating it.

The `.xlsx` file itself is limited to exactly 10 MiB, and the complete multipart request envelope
is limited to 11 MiB to allow normal form-data overhead while rejecting oversized requests before
multipart parsing. The `Cases` worksheet can contain at most 10,000 data rows (not including the
header). Before openpyxl reads a workbook, AgentGate also rejects ZIP packages with more than
100 MiB total uncompressed data, any entry larger than 50 MiB uncompressed, or any entry whose
compression ratio exceeds 200:1. These conservative archive limits protect against obvious ZIP
bombs; unusually high-compression legitimate workbooks may require the thresholds to be tuned.

Dataset name and description are not workbook columns. Supply them in the Web import dialog or as
multipart request fields. Import assigns a new Dataset ID while preserving the Case, Turn, and
Expectation IDs from the workbook. It always creates a Draft and requires a manual publish step.

### REST API

Import uses multipart form data with a required Excel file and Dataset name; the description is
optional:

```bash
curl -X POST http://localhost:8000/api/datasets/import/excel \
  -F 'file=@loan-cases.xlsx;type=application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' \
  -F 'name=Loan regression suite' \
  -F 'description=Multi-turn loan evaluation cases'
```

Excel export is available only for a published Dataset version. It downloads an `.xlsx` workbook
without changing JSON export behavior:

```bash
curl --fail --output loan-regression-v1.xlsx \
  http://localhost:8000/api/datasets/<dataset_id>/versions/1/export/excel
```
