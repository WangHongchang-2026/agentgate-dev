"""XLSX import/export for Dataset cases."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
import json
from json import JSONDecodeError
from typing import Any
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError

from agentgate.domain import Case, DatasetVersion
from agentgate.domain.base import thaw_json


SHEET_NAME = "Cases"
HEADERS = (
    "case_id", "case_name", "case_description", "category", "difficulty",
    "tags_json", "initial_state_json", "turn_id", "turn_order", "input_json",
    "expected_skill", "expectations_json", "required_tools_json", "forbidden_tools_json",
    "policy_rules_json", "turn_notes",
)
JSON_DEFAULTS: dict[str, Any] = {
    "tags_json": [],
    "initial_state_json": {},
    "input_json": {},
    "expectations_json": [],
    "required_tools_json": [],
    "forbidden_tools_json": [],
    "policy_rules_json": [],
}
OPTIONAL_DEFAULTS = {
    "case_description": "",
    "category": "positive",
    "difficulty": "medium",
    "expected_skill": None,
    "turn_notes": "",
}
REQUIRED_COLUMNS = (
    "case_id", "case_name", "turn_id", "turn_order", "input_json", "expectations_json",
)
REQUIRED_NON_JSON_COLUMNS = ("case_id", "case_name", "turn_id", "turn_order")
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_DATA_ROWS = 10_000


@dataclass(frozen=True, slots=True)
class ExcelImportIssue:
    sheet: str
    row: int | None
    column: str | None
    message: str


class DatasetExcelValidationError(ValueError):
    """All structural and model-validation errors found in an XLSX upload."""

    def __init__(self, issues: tuple[ExcelImportIssue, ...]) -> None:
        self.issues = issues
        details = "; ".join(
            f"{issue.sheet}!{issue.column or '*'}"
            f"{f' row {issue.row}' if issue.row is not None else ''}: {issue.message}"
            for issue in issues
        )
        super().__init__(details or "Excel workbook validation failed")


@dataclass(slots=True)
class _Row:
    number: int
    cells: dict[str, Any]
    turn_order: int | None


def build_excel(version: DatasetVersion) -> bytes:
    """Serialize a DatasetVersion's Cases to the stable single-sheet XLSX format."""
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(SHEET_NAME)
    sheet.append(HEADERS)
    for case in version.cases:
        for turn_order, turn in enumerate(case.turns, start=1):
            sheet.append((
                case.id,
                case.name,
                case.notes,
                case.category.value,
                case.difficulty.value,
                _compact_json(case.tags),
                _compact_json(case.initial_state),
                turn.id,
                turn_order,
                _compact_json(turn.input),
                turn.expected_skill,
                _compact_json([item.model_dump(mode="json") for item in turn.expectations]),
                _compact_json(turn.required_tools),
                _compact_json(turn.forbidden_tools),
                _compact_json(turn.policy_rules),
                turn.notes,
            ))
    content = BytesIO()
    workbook.save(content)
    return content.getvalue()


def parse_excel(content: bytes) -> tuple[Case, ...]:
    """Parse a Cases worksheet, collecting all independently discoverable issues."""
    if len(content) > MAX_INPUT_BYTES:
        raise DatasetExcelValidationError((ExcelImportIssue(
            SHEET_NAME, None, None, f"input exceeds {MAX_INPUT_BYTES} byte limit"
        ),))
    workbook = None
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        if SHEET_NAME not in workbook.sheetnames:
            raise DatasetExcelValidationError((ExcelImportIssue(
                SHEET_NAME, None, None, f"required worksheet '{SHEET_NAME}' is missing"
            ),))
        sheet = workbook[SHEET_NAME]
        rows = sheet.iter_rows(values_only=True)
        header = tuple(next(rows, ()))
        header_issues = _header_issues(header)
        if header_issues:
            raise DatasetExcelValidationError(tuple(header_issues))

        issues: list[ExcelImportIssue] = []
        cases: dict[str, list[_Row]] = {}
        anonymous_cases: list[list[_Row]] = []
        for row_number, values in enumerate(rows, start=2):
            if row_number > MAX_DATA_ROWS + 1:
                issues.append(ExcelImportIssue(
                    SHEET_NAME, row_number, None,
                    f"worksheet exceeds {MAX_DATA_ROWS} data row limit",
                ))
                break
            cells = dict(zip(HEADERS, values, strict=True))
            parsed = _parse_row(cells, row_number, issues)
            case_id = parsed.cells["case_id"]
            if not _is_blank(case_id):
                cases.setdefault(str(case_id), []).append(parsed)
            else:
                anonymous_cases.append([parsed])

        output: list[Case] = []
        for case_rows in [*cases.values(), *anonymous_cases]:
            _validate_case_structure(case_rows, issues)
            parsed_case = _build_case(case_rows, issues)
            if parsed_case is not None:
                output.append(parsed_case)

        if issues:
            raise DatasetExcelValidationError(tuple(issues))
        return tuple(output)
    except DatasetExcelValidationError:
        raise
    except (BadZipFile, InvalidFileException, OSError, ParseError, ValueError) as exc:
        raise DatasetExcelValidationError((ExcelImportIssue(
            SHEET_NAME, None, None, f"invalid XLSX content: {exc}"
        ),)) from exc
    finally:
        if workbook is not None:
            workbook.close()


def _compact_json(value: Any) -> str:
    return json.dumps(thaw_json(value), ensure_ascii=False, separators=(",", ":"))


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _header_issues(header: tuple[Any, ...]) -> list[ExcelImportIssue]:
    issues: list[ExcelImportIssue] = []
    for index, expected in enumerate(HEADERS):
        actual = header[index] if index < len(header) else None
        if actual != expected:
            issues.append(ExcelImportIssue(
                SHEET_NAME, 1, expected, f"expected header '{expected}'"
            ))
    for actual in header[len(HEADERS):]:
        issues.append(ExcelImportIssue(
            SHEET_NAME, 1, str(actual) if actual is not None else None, "unexpected header"
        ))
    return issues


def _parse_row(
    raw_cells: dict[str, Any], row: int, issues: list[ExcelImportIssue],
) -> _Row:
    cells = dict(raw_cells)
    for column, default in OPTIONAL_DEFAULTS.items():
        if _is_blank(cells[column]):
            cells[column] = default
    for column in REQUIRED_NON_JSON_COLUMNS:
        if _is_blank(cells[column]):
            issues.append(ExcelImportIssue(SHEET_NAME, row, column, "value is required"))

    for column, default in JSON_DEFAULTS.items():
        required = column in REQUIRED_COLUMNS
        cells[column] = _parse_json_cell(cells[column], column, row, required, default, issues)
    turn_order = _parse_turn_order(cells["turn_order"], row, issues)
    return _Row(row, cells, turn_order)


def _parse_json_cell(
    value: Any,
    column: str,
    row: int,
    required: bool,
    default: Any,
    issues: list[ExcelImportIssue],
) -> Any:
    if _is_blank(value):
        if required:
            issues.append(ExcelImportIssue(SHEET_NAME, row, column, "value is required"))
        return default
    if not isinstance(value, str):
        issues.append(ExcelImportIssue(SHEET_NAME, row, column, "must contain JSON text"))
        return default
    try:
        return json.loads(value)
    except JSONDecodeError as exc:
        issues.append(ExcelImportIssue(SHEET_NAME, row, column, f"invalid JSON: {exc.msg}"))
        return default


def _parse_turn_order(value: Any, row: int, issues: list[ExcelImportIssue]) -> int | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool):
        issues.append(ExcelImportIssue(SHEET_NAME, row, "turn_order", "must be an integer"))
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    issues.append(ExcelImportIssue(SHEET_NAME, row, "turn_order", "must be an integer"))
    return None


def _validate_case_structure(rows: list[_Row], issues: list[ExcelImportIssue]) -> None:
    first = rows[0]
    for row in rows[1:]:
        for column in (
            "case_name", "case_description", "category", "difficulty", "tags_json",
            "initial_state_json",
        ):
            if row.cells[column] != first.cells[column]:
                issues.append(ExcelImportIssue(
                    SHEET_NAME, row.number, column,
                    f"conflicts with the first row for case_id '{first.cells['case_id']}'",
                ))

    seen_turn_ids: set[str] = set()
    seen_orders: set[int] = set()
    for row in rows:
        turn_id = row.cells["turn_id"]
        if not _is_blank(turn_id):
            if str(turn_id) in seen_turn_ids:
                issues.append(ExcelImportIssue(
                    SHEET_NAME, row.number, "turn_id", "duplicate turn_id within Case"
                ))
            seen_turn_ids.add(str(turn_id))
        if row.turn_order is not None:
            if row.turn_order in seen_orders:
                issues.append(ExcelImportIssue(
                    SHEET_NAME, row.number, "turn_order", "duplicate turn_order within Case"
                ))
            seen_orders.add(row.turn_order)

    ordered = sorted((row.turn_order for row in rows if row.turn_order is not None))
    if len(ordered) == len(rows) and ordered != list(range(1, len(rows) + 1)):
        valid_orders = range(1, len(rows) + 1)
        offender = next((row for row in rows if row.turn_order not in valid_orders), rows[-1])
        issues.append(ExcelImportIssue(
            SHEET_NAME, offender.number, "turn_order", "must be 1-based and contiguous per Case"
        ))


def _build_case(rows: list[_Row], issues: list[ExcelImportIssue]) -> Case | None:
    ordered_rows = sorted(rows, key=lambda row: (
        row.turn_order is None,
        row.turn_order if row.turn_order is not None else row.number,
    ))
    first = ordered_rows[0]
    payload = {
        "id": first.cells["case_id"],
        "name": first.cells["case_name"],
        "notes": first.cells["case_description"],
        "category": first.cells["category"],
        "difficulty": first.cells["difficulty"],
        "tags": first.cells["tags_json"],
        "initial_state": first.cells["initial_state_json"],
        "turns": [
            {
                "id": row.cells["turn_id"],
                "input": row.cells["input_json"],
                "expected_skill": row.cells["expected_skill"],
                "expectations": row.cells["expectations_json"],
                "required_tools": row.cells["required_tools_json"],
                "forbidden_tools": row.cells["forbidden_tools_json"],
                "policy_rules": row.cells["policy_rules_json"],
                "notes": row.cells["turn_notes"],
            }
            for row in ordered_rows
        ],
    }
    try:
        return Case.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors():
            row, column = _validation_location(error["loc"], first.number, ordered_rows)
            issues.append(ExcelImportIssue(SHEET_NAME, row, column, error["msg"]))
        return None


def _validation_location(
    location: Iterable[Any], first_row: int, rows: list[_Row],
) -> tuple[int, str | None]:
    parts = tuple(location)
    case_columns = {
        "id": "case_id", "name": "case_name", "notes": "case_description",
        "category": "category", "difficulty": "difficulty", "tags": "tags_json",
        "initial_state": "initial_state_json",
    }
    turn_columns = {
        "id": "turn_id", "input": "input_json", "expected_skill": "expected_skill",
        "expectations": "expectations_json", "required_tools": "required_tools_json",
        "forbidden_tools": "forbidden_tools_json", "policy_rules": "policy_rules_json",
        "notes": "turn_notes",
    }
    if len(parts) >= 3 and parts[0] == "turns" and isinstance(parts[1], int):
        return rows[parts[1]].number, turn_columns.get(str(parts[2]))
    return first_row, case_columns.get(str(parts[0])) if parts else None
