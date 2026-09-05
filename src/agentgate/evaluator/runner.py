"""Evaluator execution with per-turn checks, memoization, and error Results."""

from __future__ import annotations

import logging
import re
from typing import Any

from agentgate.domain import Case, EvaluationResult, EvaluatorErrorDetail, EvaluatorSpec, Outcome, Trace

from .calc_score import calculate_result
from .models import (
    CircularEvaluatorDependency, DuplicateEvaluatorId, Evaluation,
    MissingEvaluatorDependency,
)
from .registry import resolve_evaluator

LOGGER = logging.getLogger(__name__)


def _safe_message(exc: Exception) -> str:
    message = str(exc).strip()[:500] or type(exc).__name__
    return re.sub(
        r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+",
        r"\1=[redacted]",
        message,
    )


def _error_result(spec: EvaluatorSpec, case: Case, trace: Trace, exc: Exception) -> EvaluationResult:
    category = "timeout" if isinstance(exc, TimeoutError) else (
        "invalid_output" if isinstance(exc, (TypeError, ValueError)) else "crash"
    )
    LOGGER.exception("evaluator %s failed for case %s", spec.id, case.id)
    return EvaluationResult(
        run_id=trace.run_id,
        trace_id=trace.trace_id,
        case_id=case.id,
        evaluator_id=spec.id,
        evaluator_name=spec.name,
        evaluator_version=spec.version,
        evaluator_content_sha256=spec.content_sha256,
        evaluator_kind=spec.kind,
        dimension=spec.dimension,
        metric=spec.metric,
        severity=spec.severity,
        outcome=Outcome.ERROR,
        score=None,
        reason="评估器无法完成检查",
        error_detail=EvaluatorErrorDetail(
            category=category,
            exception_type=type(exc).__name__,
            message=_safe_message(exc),
            retryable=category == "timeout",
        ),
    )


def evaluate_case(
    case: Case, trace: Trace, evaluators: tuple[EvaluatorSpec, ...]
) -> list[EvaluationResult]:
    by_id = {item.id: item for item in evaluators}
    if len(by_id) != len(evaluators):
        raise DuplicateEvaluatorId("evaluator IDs must be unique")

    cache: dict[str, EvaluationResult] = {}
    resolving: set[str] = set()

    def resolve(spec_id: str) -> EvaluationResult:
        if spec_id in cache:
            return cache[spec_id]
        if spec_id not in by_id:
            raise MissingEvaluatorDependency(spec_id)
        if spec_id in resolving:
            raise CircularEvaluatorDependency(spec_id)
        resolving.add(spec_id)
        spec = by_id[spec_id]
        try:
            implementation = resolve_evaluator(spec)
            checks = []
            judge_record = None
            for turn in case.turns:
                turn_trace = trace.for_turn(turn.id)
                if not implementation.applies_to(spec, turn):
                    continue
                turn_evaluation: Any = implementation.evaluate(
                    spec, turn, turn_trace, resolve
                )
                if not isinstance(turn_evaluation, Evaluation):
                    raise TypeError("evaluator returned malformed Evaluation")
                checks.extend(
                    check if check.turn_id else check.model_copy(update={"turn_id": turn.id})
                    for check in turn_evaluation.checks
                )
                judge_record = turn_evaluation.judge_record or judge_record
            evaluation = Evaluation(checks=tuple(checks), judge_record=judge_record)
            result = calculate_result(spec, trace.run_id, case.id, trace, evaluation)
        except Exception as exc:
            result = _error_result(spec, case, trace, exc)
        finally:
            resolving.discard(spec_id)
        cache[spec_id] = result
        return result

    return [resolve(item.id) for item in evaluators]
