"""Deterministic comparison operators used by Rule evaluators."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeAlias

from agentgate.domain import (
    Condition,
    Equals,
    MatchesJsonSchema,
    MatchesPattern,
    MethodRef,
    MustBeMissing,
    OneOf,
    WithinRange,
    WithinTolerance,
)

from .json_schema import json_schema_failure_reason
from .observations import MISSING


_MAX_REASON_LENGTH = 500


class OperatorError(ValueError):
    """Base error for deterministic operator resolution."""


class UnknownOperator(OperatorError):
    """Raised when an operator ID or exact version is unavailable."""


class UnsupportedOperator(OperatorError):
    """Raised when a recognized Condition has no implemented operator."""


@dataclass(frozen=True, slots=True)
class OperatorOutcome:
    """One deterministic comparison conclusion."""

    passed: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise TypeError("OperatorOutcome passed must be a boolean")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("OperatorOutcome reason must not be blank")
        if len(self.reason) > _MAX_REASON_LENGTH:
            raise ValueError("OperatorOutcome reason must not exceed 500 characters")


OperatorFunction: TypeAlias = Callable[[Any, Any], OperatorOutcome]


def _bounded_reason(reason: str) -> str:
    if len(reason) <= _MAX_REASON_LENGTH:
        return reason
    return f"{reason[: _MAX_REASON_LENGTH - 1].rstrip()}…"


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _string_collection(value: Any, name: str) -> Collection[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Collection):
        raise TypeError(f"{name} must be a collection of strings")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"{name} must contain only strings")
    return value


def equals(actual: Any, condition: Equals) -> OperatorOutcome:
    passed = actual is not MISSING and actual == condition.expected
    reason = "值相等" if passed else "实际值与预期值不相等"
    return OperatorOutcome(passed=passed, reason=reason)


def within_tolerance(
    actual: Any,
    condition: WithinTolerance,
) -> OperatorOutcome:
    passed = _numeric(actual) and (
        abs(float(actual) - condition.expected) <= condition.epsilon
    )
    reason = "数值在容差内" if passed else "数值超出允许容差"
    return OperatorOutcome(passed=passed, reason=reason)


def within_range(actual: Any, condition: WithinRange) -> OperatorOutcome:
    passed = _numeric(actual)
    if passed and condition.minimum is not None:
        passed = actual >= condition.minimum
    if passed and condition.maximum is not None:
        passed = actual <= condition.maximum
    reason = "数值在范围内" if passed else "数值不在允许范围内"
    return OperatorOutcome(passed=passed, reason=reason)


def matches_pattern(actual: Any, condition: MatchesPattern) -> OperatorOutcome:
    passed = isinstance(actual, str) and re.search(condition.pattern, actual) is not None
    reason = "文本符合格式" if passed else "文本不符合格式"
    return OperatorOutcome(passed=passed, reason=reason)


def is_one_of(actual: Any, condition: OneOf) -> OperatorOutcome:
    passed = actual is not MISSING and actual in condition.allowed
    reason = "值在允许集合中" if passed else "值不在允许集合中"
    return OperatorOutcome(passed=passed, reason=reason)


def must_be_missing(actual: Any, _condition: MustBeMissing) -> OperatorOutcome:
    passed = actual is MISSING
    reason = "字段不存在" if passed else "字段存在但预期不存在"
    return OperatorOutcome(passed=passed, reason=reason)


def matches_json_schema(
    actual: Any,
    condition: MatchesJsonSchema,
) -> OperatorOutcome:
    if actual is MISSING:
        return OperatorOutcome(passed=False, reason="JSON value is missing")
    failure_reason = json_schema_failure_reason(actual, condition.json_schema)
    return OperatorOutcome(
        passed=failure_reason is None,
        reason=failure_reason or "value matches JSON Schema",
    )


def contains_all(actual: Collection[str], expected: Collection[str]) -> OperatorOutcome:
    actual_values = _string_collection(actual, "actual")
    expected_values = _string_collection(expected, "expected")
    missing = [item for item in expected_values if item not in actual_values]
    reason = "包含所有必需项" if not missing else f"缺少：{', '.join(missing)}"
    return OperatorOutcome(passed=not missing, reason=_bounded_reason(reason))


def contains_none(actual: Collection[str], forbidden: Collection[str]) -> OperatorOutcome:
    actual_values = _string_collection(actual, "actual")
    forbidden_values = _string_collection(forbidden, "forbidden")
    found = [item for item in forbidden_values if item in actual_values]
    reason = "未包含禁用项" if not found else f"包含禁用项：{', '.join(found)}"
    return OperatorOutcome(passed=not found, reason=_bounded_reason(reason))


_OPERATOR_IMPLEMENTATIONS = MappingProxyType({
    ("equals", "1"): equals,
    ("within_tolerance", "1"): within_tolerance,
    ("within_range", "1"): within_range,
    ("matches_pattern", "1"): matches_pattern,
    ("is_one_of", "1"): is_one_of,
    ("must_be_missing", "1"): must_be_missing,
    ("matches_json_schema", "1"): matches_json_schema,
    ("contains_all", "1"): contains_all,
    ("contains_none", "1"): contains_none,
})

_CONDITION_OPERATOR_IDS = MappingProxyType({
    "equals": "equals",
    "within_tolerance": "within_tolerance",
    "within_range": "within_range",
    "matches_pattern": "matches_pattern",
    "one_of": "is_one_of",
    "must_be_missing": "must_be_missing",
    "matches_json_schema": "matches_json_schema",
})


def resolve_operator(
    implementation_id: str,
    implementation_version: str,
) -> OperatorFunction:
    """Return the exact deterministic operator implementation."""

    implementation = _OPERATOR_IMPLEMENTATIONS.get(
        (implementation_id, implementation_version)
    )
    if implementation is None:
        raise UnknownOperator(
            f"unknown operator: {implementation_id}@{implementation_version}"
        )
    return implementation


def resolve_condition_operator(
    condition: Condition,
    implementation_version: str = "1",
) -> tuple[MethodRef, OperatorFunction]:
    """Resolve exact operator provenance and behavior for one Condition."""

    implementation_id = _CONDITION_OPERATOR_IDS.get(condition.kind)
    if implementation_id is None:
        raise UnsupportedOperator(f"unsupported condition: {condition.kind}")
    method = MethodRef(
        implementation_id=implementation_id,
        implementation_version=implementation_version,
    )
    return method, resolve_operator(implementation_id, implementation_version)
