"""Execute explicitly composed evaluators for one completed Case."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import cast

from agentgate.domain import (
    Case,
    CheckResult,
    EvaluationResult,
    EvaluatorErrorDetail,
    EvaluatorKind,
    EvaluatorSpec,
    Outcome,
    Trace,
)

from .evaluator_protocol import (
    CaseEvaluatorProtocol,
    EvaluatorProtocol,
    TurnEvaluatorProtocol,
)
from .models import (
    CheckDraft,
    CircularEvaluatorDependency,
    DuplicateEvaluatorId,
    Evaluation,
    EvaluatorKindMismatch,
    EvaluatorVersionMismatch,
    MissingEvaluatorDependency,
    ResultResolver,
    UnknownEvaluator,
)


LOGGER = logging.getLogger(__name__)

EvaluatorImplementations = Mapping[tuple[str, str], EvaluatorProtocol]


def _safe_message(exc: Exception) -> str:
    message = str(exc).strip()[:500] or type(exc).__name__
    return re.sub(
        r"(?i)(api[_-]?key|authorization|token|secret|password)\s*[=:]\s*\S+",
        r"\1=[redacted]",
        message,
    )


def _error_result(
    spec: EvaluatorSpec,
    case: Case,
    trace: Trace,
    exc: Exception,
) -> EvaluationResult:
    category = (
        "timeout"
        if isinstance(exc, TimeoutError)
        else "invalid_output"
        if isinstance(exc, (TypeError, ValueError))
        else "crash"
    )
    message = _safe_message(exc)
    LOGGER.error(
        "evaluator %s failed for case %s: %s: %s",
        spec.id,
        case.id,
        type(exc).__name__,
        message,
    )
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
            message=message,
            retryable=category == "timeout",
        ),
    )


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


def _finalize_evaluation(
    spec: EvaluatorSpec,
    case: Case,
    trace: Trace,
    evaluation: Evaluation,
) -> EvaluationResult:
    checks = tuple(_finalize_check(item, trace) for item in evaluation.checks)
    applicable = tuple(item for item in checks if item.outcome != Outcome.NOT_APPLICABLE)
    if not applicable:
        outcome, score, reason = Outcome.NOT_APPLICABLE, None, "该用例没有适用检查"
    else:
        failed = tuple(item for item in applicable if item.outcome == Outcome.FAIL)
        reviewed = tuple(item for item in applicable if item.outcome == Outcome.REVIEW)
        score = sum(item.score or 0.0 for item in applicable) / len(applicable)
        if failed:
            outcome, reason = Outcome.FAIL, "；".join(item.reason for item in failed)
        elif reviewed:
            outcome, reason = Outcome.REVIEW, "需要人工复核"
        else:
            outcome, reason = Outcome.PASS, "所有适用检查均通过"

    failed_checks = tuple(item for item in checks if item.outcome == Outcome.FAIL)
    primary_failure_stage = (
        min(
            enumerate(failed_checks),
            key=lambda pair: (pair[1].failure_sequence, pair[0]),
        )[1].failure_stage
        if failed_checks
        else None
    )
    return EvaluationResult(
        run_id=trace.run_id,
        case_id=case.id,
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
        primary_failure_stage=primary_failure_stage,
    )


def _validate_implementation(
    spec: EvaluatorSpec,
    implementations: EvaluatorImplementations,
) -> EvaluatorProtocol:
    key = (spec.implementation_id, spec.implementation_version)
    implementation = implementations.get(key)
    if implementation is None:
        raise UnknownEvaluator(
            f"unknown evaluator implementation: {spec.implementation_id}@{spec.implementation_version}"
        )
    if implementation.implementation_id != spec.implementation_id:
        raise UnknownEvaluator(
            f"implementation key {key!r} does not match {implementation.implementation_id!r}"
        )
    if implementation.implementation_version != spec.implementation_version:
        raise EvaluatorVersionMismatch(
            f"{spec.implementation_id} requires version {spec.implementation_version}, "
            f"not {implementation.implementation_version}"
        )
    if implementation.kind != spec.kind:
        raise EvaluatorKindMismatch(
            f"{spec.implementation_id} implements {implementation.kind}, not {spec.kind}"
        )
    return implementation


def _validate_turn_evaluation(
    evaluation: Evaluation,
    turn_id: str,
    trace: Trace,
) -> tuple[CheckDraft, ...]:
    trace_span_ids = {span.span_id for span in trace.spans}
    checks: list[CheckDraft] = []
    for check in evaluation.checks:
        if check.turn_id is not None and check.turn_id != turn_id:
            raise ValueError(
                f"evaluator check turn_id {check.turn_id!r} does not match {turn_id!r}"
            )
        unknown_span_ids = set(check.span_ids).difference(trace_span_ids)
        if check.failure and check.failure.span_id:
            unknown_span_ids.difference_update({check.failure.span_id})
            if check.failure.span_id not in trace_span_ids:
                unknown_span_ids.add(check.failure.span_id)
        if unknown_span_ids:
            unknown = ", ".join(sorted(unknown_span_ids))
            raise ValueError(f"evaluator check references unknown spans: {unknown}")
        checks.append(
            check if check.turn_id is not None else check.model_copy(update={"turn_id": turn_id})
        )
    return tuple(checks)


def _validate_case_evaluation(
    evaluation: Evaluation,
    case: Case,
    trace: Trace,
) -> tuple[CheckDraft, ...]:
    turn_ids = {turn.id for turn in case.turns}
    trace_span_ids = {span.span_id for span in trace.spans}
    checks: list[CheckDraft] = []
    for check in evaluation.checks:
        if check.turn_id is not None and check.turn_id not in turn_ids:
            raise ValueError(
                f"evaluator check references unknown Case turn: {check.turn_id!r}"
            )
        unknown_span_ids = set(check.span_ids).difference(trace_span_ids)
        if check.failure and check.failure.span_id:
            unknown_span_ids.difference_update({check.failure.span_id})
            if check.failure.span_id not in trace_span_ids:
                unknown_span_ids.add(check.failure.span_id)
        if unknown_span_ids:
            unknown = ", ".join(sorted(unknown_span_ids))
            raise ValueError(f"evaluator check references unknown spans: {unknown}")
        checks.append(check)
    return tuple(checks)


def _require_turn_evaluator(
    implementation: EvaluatorProtocol,
) -> TurnEvaluatorProtocol:
    if not callable(getattr(implementation, "applies_to", None)) or not callable(
        getattr(implementation, "evaluate", None)
    ):
        raise TypeError("turn-scoped evaluator must define applies_to and evaluate")
    return cast(TurnEvaluatorProtocol, implementation)


def _require_case_evaluator(
    implementation: EvaluatorProtocol,
) -> CaseEvaluatorProtocol:
    if not callable(getattr(implementation, "evaluate_case", None)):
        raise TypeError("LLM Judge evaluator must define evaluate_case")
    return cast(CaseEvaluatorProtocol, implementation)


def execute_evaluators(
    case: Case,
    trace: Trace,
    evaluator_specs: tuple[EvaluatorSpec, ...],
    implementations: EvaluatorImplementations,
) -> tuple[EvaluationResult, ...]:
    """Execute selected evaluator implementations for one completed Case."""

    if trace.case_id != case.id:
        raise ValueError(
            f"Trace case_id {trace.case_id!r} does not match Case id {case.id!r}"
        )

    specs_by_id = {spec.id: spec for spec in evaluator_specs}
    if len(specs_by_id) != len(evaluator_specs):
        raise DuplicateEvaluatorId("evaluator IDs must be unique")

    resolved_implementations = {
        spec.id: _validate_implementation(spec, implementations)
        for spec in evaluator_specs
    }
    cache: dict[str, EvaluationResult] = {}
    resolving: set[str] = set()

    def resolve(spec_id: str) -> EvaluationResult:
        if spec_id in cache:
            return cache[spec_id]
        if spec_id not in specs_by_id:
            raise MissingEvaluatorDependency(spec_id)
        if spec_id in resolving:
            raise CircularEvaluatorDependency(spec_id)

        resolving.add(spec_id)
        spec = specs_by_id[spec_id]
        implementation = resolved_implementations[spec_id]
        try:
            checks: list[CheckDraft] = []
            judge_record = None
            declared_dependencies = {
                child.evaluator_id: child for child in spec.children
            }

            def resolve_dependency(dependency_id: str) -> EvaluationResult:
                dependency = declared_dependencies.get(dependency_id)
                if dependency is None:
                    raise MissingEvaluatorDependency(
                        f"{spec.id} did not declare dependency {dependency_id}"
                    )
                dependency_spec = specs_by_id.get(dependency_id)
                if dependency_spec is None:
                    raise MissingEvaluatorDependency(dependency_id)
                if dependency.evaluator_version != dependency_spec.version:
                    raise EvaluatorVersionMismatch(
                        f"{dependency_id} requires evaluator version "
                        f"{dependency.evaluator_version}, not {dependency_spec.version}"
                    )
                return resolve(dependency_id)

            resolver: ResultResolver = resolve_dependency
            if spec.kind == EvaluatorKind.LLM_JUDGE:
                case_implementation = _require_case_evaluator(implementation)
                case_evaluation = case_implementation.evaluate_case(
                    spec,
                    case,
                    trace,
                    resolver,
                )
                if not isinstance(case_evaluation, Evaluation):
                    raise TypeError("evaluator returned malformed Evaluation")
                checks.extend(_validate_case_evaluation(case_evaluation, case, trace))
                judge_record = case_evaluation.judge_record
            else:
                turn_implementation = _require_turn_evaluator(implementation)
                for turn in case.turns:
                    turn_trace = trace.for_turn(turn.id)
                    if not turn_implementation.applies_to(spec, turn):
                        continue
                    turn_evaluation = turn_implementation.evaluate(
                        spec,
                        turn,
                        turn_trace,
                        resolver,
                    )
                    if not isinstance(turn_evaluation, Evaluation):
                        raise TypeError("evaluator returned malformed Evaluation")
                    checks.extend(
                        _validate_turn_evaluation(turn_evaluation, turn.id, turn_trace)
                    )
                    if turn_evaluation.judge_record is not None:
                        if judge_record is not None:
                            raise ValueError("evaluator returned multiple Judge records")
                        judge_record = turn_evaluation.judge_record

            evaluation = Evaluation(checks=tuple(checks), judge_record=judge_record)
            result = _finalize_evaluation(spec, case, trace, evaluation)
        except Exception as exc:
            result = _error_result(spec, case, trace, exc)
        finally:
            resolving.discard(spec_id)
        cache[spec_id] = result
        return result

    return tuple(resolve(spec.id) for spec in evaluator_specs)
