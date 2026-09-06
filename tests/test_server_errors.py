from __future__ import annotations

import pytest
from fastapi import HTTPException

from agentgate.dataset.formats.xlsx import XlsxFormatError, XlsxIssue
from agentgate.server.errors import (
    raise_conflict,
    raise_not_found,
    raise_unprocessable,
    raise_xlsx_error,
)


@pytest.mark.parametrize(
    "function,status_code",
    [
        (raise_not_found, 404),
        (raise_unprocessable, 422),
        (raise_conflict, 409),
    ],
)
def test_error_helpers_use_explicit_status_and_redact_credentials(
    function, status_code
) -> None:
    with pytest.raises(HTTPException) as raised:
        function(ValueError("request failed api_key=private-value"))

    assert raised.value.status_code == status_code
    assert "private-value" not in raised.value.detail
    assert "api_key=[redacted]" in raised.value.detail


def test_xlsx_error_preserves_bounded_structured_locations() -> None:
    error = XlsxFormatError((
        XlsxIssue("Cases", 4, "input_json", "invalid JSON"),
        XlsxIssue("Cases", 8, None, "token=private-value"),
    ))

    with pytest.raises(HTTPException) as raised:
        raise_xlsx_error(error)

    assert raised.value.status_code == 422
    assert raised.value.detail == {
        "code": "xlsx_validation_failed",
        "issue_count": 2,
        "issues": [
            {
                "sheet": "Cases",
                "row": 4,
                "column": "input_json",
                "message": "invalid JSON",
            },
            {
                "sheet": "Cases",
                "row": 8,
                "column": None,
                "message": "token=[redacted]",
            },
        ],
    }


def test_error_detail_is_bounded() -> None:
    with pytest.raises(HTTPException) as raised:
        raise_unprocessable(ValueError("x" * 1_000))

    assert len(raised.value.detail) == 500
