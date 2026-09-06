"""Stable conversion from known application failures to HTTP errors."""

from __future__ import annotations

import re
from typing import NoReturn

from fastapi import HTTPException

from agentgate.dataset.formats.xlsx import XlsxFormatError


_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|token|secret|password)\s*[=:]\s*\S+"
)


def raise_not_found(error: Exception) -> NoReturn:
    raise HTTPException(status_code=404, detail=_safe_message(error)) from error


def raise_unprocessable(error: Exception) -> NoReturn:
    raise HTTPException(status_code=422, detail=_safe_message(error)) from error


def raise_conflict(error: Exception) -> NoReturn:
    raise HTTPException(status_code=409, detail=_safe_message(error)) from error


def raise_xlsx_error(error: XlsxFormatError) -> NoReturn:
    issues = [
        {
            "sheet": issue.sheet,
            "row": issue.row,
            "column": issue.column,
            "message": _safe_text(issue.message),
        }
        for issue in error.issues
    ]
    raise HTTPException(
        status_code=422,
        detail={
            "code": "xlsx_validation_failed",
            "issue_count": len(issues),
            "issues": issues,
        },
    ) from error


def _safe_message(error: Exception) -> str:
    return _safe_text(str(error).strip() or type(error).__name__)


def _safe_text(value: str) -> str:
    return _CREDENTIAL_PATTERN.sub(r"\1=[redacted]", value)[:500]
