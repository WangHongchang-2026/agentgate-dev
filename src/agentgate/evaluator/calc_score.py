"""Convert runtime evaluator checks into one persisted EvaluationResult."""

from __future__ import annotations

from agentgate.domain import (
    CheckResult,
    EvaluationResult,
    EvaluatorSpec,
    Outcome,
    Trace,
)

from .models import CheckDraft, Evaluation


def _finalize_check(draft: CheckDraft, trace: Trace) -> CheckResult:
    failure_stage = None
    failure_sequence = None
    failure_span_id = None
    if draft.outcome == Outcome.FAIL:
        if draft.failure is None:
            raise ValueError("failed check has no failure candidate")
        failure_stage = draft.failure.stage
        failure_span_id = draft.failure.span_id
        if failure_span_id:
            span = next(
                (item for item in trace.spans if item.span_id == failure_span_id),
                None,
            )
            if span is None:
                raise ValueError(f"failure references unknown span: {failure_span_id}")
            failure_sequence = span.sequence
        else:
            failure_sequence = trace.completion_sequence()

    span_ids = draft.span_ids
    if failure_span_id and failure_span_id not in span_ids:
        span_ids = (*span_ids, failure_span_id)

    return CheckResult(
        name=draft.name,
        turn_id=draft.turn_id,
        expectation_id=draft.expectation_id,
        outcome=draft.outcome,
        score=draft.score,
        reason=draft.reason,
        expected=draft.expected,
        actual=draft.actual,
        actual_missing=draft.actual_missing,
        methods=draft.methods,
        span_ids=span_ids,
        failure_stage=failure_stage,
        failure_sequence=failure_sequence,
        failure_span_id=failure_span_id,
    )


def calculate_result(
    spec: EvaluatorSpec,
    run_id: str,
    case_id: str,
    trace: Trace,
    evaluation: Evaluation,
) -> EvaluationResult:
    checks = tuple(_finalize_check(item, trace) for item in evaluation.checks)
    applicable = [item for item in checks if item.outcome != Outcome.NOT_APPLICABLE]
    if not applicable:
        outcome, score, reason = Outcome.NOT_APPLICABLE, None, "该用例没有适用检查"
    else:
        failed = [item for item in applicable if item.outcome == Outcome.FAIL]
        reviewed = [item for item in applicable if item.outcome == Outcome.REVIEW]
        score = sum(item.score or 0.0 for item in applicable) / len(applicable)
        if failed:
            outcome, reason = Outcome.FAIL, "；".join(item.reason for item in failed)
        elif reviewed:
            outcome, reason = Outcome.REVIEW, "需要人工复核"
        else:
            outcome, reason = Outcome.PASS, "所有适用检查均通过"

    failed_checks = tuple(item for item in checks if item.outcome == Outcome.FAIL)
    primary = (
        min(
            enumerate(failed_checks),
            key=lambda pair: (pair[1].failure_sequence, pair[0]),
        )[1].failure_stage
        if failed_checks
        else None
    )
    return EvaluationResult(
        run_id=run_id,
        case_id=case_id,
        trace_id=trace.trace_id,
        evaluator_id=spec.id,
        evaluator_name=spec.name,
        evaluator_version=spec.version,
        evaluator_content_sha256=spec.content_sha256,
        evaluator_kind=spec.kind,
        dimension=spec.dimension,
        metric=spec.metric,
        severity=spec.severity,
        outcome=outcome,
        score=score,
        reason=reason,
        checks=checks,
        judge_record=evaluation.judge_record,
        primary_failure_stage=primary,
    )
