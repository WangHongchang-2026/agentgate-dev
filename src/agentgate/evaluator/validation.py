"""Pre-run validation for a DatasetVersion and selected evaluator definitions."""

from __future__ import annotations

from agentgate.domain import DatasetVersion, EvaluatorKind, MatchesJsonSchema

from .models import (
    DuplicateEvaluatorId, EvaluatorVersionMismatch, InvalidHybridEvaluator,
    MissingEvaluatorDependency, UnsupportedOperator,
)
from .observations import condition_operator
from .registry import resolve_evaluator, resolve_operator


def validate_evaluation_plan(dataset: DatasetVersion, evaluators: tuple) -> None:
    by_id = {item.id: item for item in evaluators}
    if len(by_id) != len(evaluators):
        raise DuplicateEvaluatorId("evaluator IDs must be unique")

    metric_dimensions: dict[str, object] = {}
    for spec in evaluators:
        previous = metric_dimensions.setdefault(spec.metric, spec.dimension)
        if previous != spec.dimension:
            raise ValueError(
                f"metric {spec.metric} cannot belong to both {previous} and {spec.dimension}"
            )
        if spec.kind == EvaluatorKind.RULE:
            operator = spec.config.get("operator")
            operator_version = spec.config.get("operator_version")
            if operator:
                resolve_operator(str(operator), str(operator_version or "1"))
        if spec.kind == EvaluatorKind.HYBRID:
            children = []
            for child in spec.children:
                child_spec = by_id.get(child.evaluator_id)
                if child_spec is None:
                    raise MissingEvaluatorDependency(child.evaluator_id)
                if child.evaluator_version != child_spec.version:
                    raise EvaluatorVersionMismatch(child.evaluator_id)
                children.append(child_spec)
            if any(item.kind == EvaluatorKind.HYBRID for item in children):
                raise InvalidHybridEvaluator("nested Hybrid is not supported")
            kinds = {item.kind for item in children}
            if not {EvaluatorKind.RULE, EvaluatorKind.LLM_JUDGE}.issubset(kinds):
                raise InvalidHybridEvaluator("Hybrid requires Rule and LLM Judge children")
        resolve_evaluator(spec)

    for case in dataset.cases:
        for turn in case.turns:
            for expectation in turn.expectations:
                condition = getattr(expectation, "condition", None)
                if condition is None:
                    continue
                if isinstance(condition, MatchesJsonSchema):
                    raise UnsupportedOperator("JSON Schema evaluation is deferred")
                resolve_operator(condition_operator(condition), "1")
