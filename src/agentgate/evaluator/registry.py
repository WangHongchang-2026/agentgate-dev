"""Temporary P1 registries for evaluator implementations and operators."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from agentgate.domain import EvaluatorSpec

from .base import Evaluator
from .models import EvaluatorKindMismatch, UnknownEvaluator, UnknownOperator

Operator = Callable[[Any, Any], Any]
E = TypeVar("E", bound=type[Evaluator])

_EVALUATORS: dict[str, type[Evaluator]] = {}
_OPERATORS: dict[str, tuple[str, Operator]] = {}


def register_evaluator(cls: E) -> E:
    _EVALUATORS[cls.implementation_id] = cls
    return cls


def register_operator(name: str, version: str = "1"):
    def decorator(function: Operator) -> Operator:
        _OPERATORS[name] = (version, function)
        return function
    return decorator


def resolve_evaluator(spec: EvaluatorSpec) -> Evaluator:
    implementation = _EVALUATORS.get(spec.implementation_id)
    if implementation is None:
        raise UnknownEvaluator(f"unknown implementation_id: {spec.implementation_id}")
    if implementation.kind != spec.kind:
        raise EvaluatorKindMismatch(
            f"{spec.implementation_id} implements {implementation.kind}, not {spec.kind}"
        )
    return implementation()


def resolve_operator(name: str, version: str | None = None) -> Operator:
    entry = _OPERATORS.get(name)
    if entry is None:
        raise UnknownOperator(f"unknown operator: {name}")
    registered_version, function = entry
    if version is not None and version != registered_version:
        raise UnknownOperator(
            f"operator {name} version {version} is unavailable; registered {registered_version}"
        )
    return function


def operator_version(name: str) -> str:
    if name not in _OPERATORS:
        raise UnknownOperator(f"unknown operator: {name}")
    return _OPERATORS[name][0]


def resolve_judge(_config: Any) -> Any:
    raise UnknownEvaluator("LLM Judge runtime is deferred to P2")
