"""Bounded redaction before protected data leaves AgentGate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agentgate.domain.base import thaw_json

_SENSITIVE_KEYS = re.compile(
    r"(^|[_-])(api[_-]?key|authorization|credential|password|secret|token)([_-]|$)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(r"(?i)(bearer\s+\S+|sk-(?:sp-)?[A-Za-z0-9_-]{8,})")
_REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    redacted_count: int


def redact(value: Any) -> RedactionResult:
    count = 0

    def visit(item: Any) -> Any:
        nonlocal count
        item = thaw_json(item)
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                if _SENSITIVE_KEYS.search(str(key)):
                    count += 1
                    result[str(key)] = _REDACTED
                else:
                    result[str(key)] = visit(child)
            return result
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, str):
            replaced, matches = _SECRET_VALUE.subn(_REDACTED, item)
            count += matches
            return replaced
        return item

    return RedactionResult(value=visit(value), redacted_count=count)
