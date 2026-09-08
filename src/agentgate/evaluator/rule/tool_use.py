"""Deterministic tool-use evaluation."""

from __future__ import annotations

from typing import Literal

from agentgate.domain import (
    CaseTurn,
    EvaluatorKind,
    EvaluatorSpec,
    FailureStage,
    MethodRef,
    Outcome,
    ToolArgumentExpectation,
    ToolCallExpectation,
    Trace,
    TraceSpan,
)

from ..models import CheckDraft, Evaluation, FailureCandidate, ResultResolver
from .observations import MISSING, observe_expectation
from .operators import resolve_condition_operator, resolve_operator


def _tool_spans(trace: Trace) -> tuple[TraceSpan, ...]:
    return tuple(
        sorted(
            (span for span in trace.spans if span.operation_type == "tool"),
            key=lambda span: span.sequence,
        )
    )


def _tool_call_expectations(
    turn: CaseTurn,
    mode: Literal["required", "forbidden"],
) -> tuple[ToolCallExpectation, ...]:
    return tuple(
        expectation
        for expectation in turn.expectations
        if isinstance(expectation, ToolCallExpectation)
        and expectation.mode == mode
    )


class RequiredToolEvaluator:
    """Evaluate required Tool calls for one Case turn."""

    kind = EvaluatorKind.RULE
    implementation_id = "required_tool"
    implementation_version = "1"

    def applies_to(self, _spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return bool(_tool_call_expectations(turn, "required"))

    def evaluate(
        self,
        _spec: EvaluatorSpec,
        turn: CaseTurn,
        trace: Trace,
        _resolve: ResultResolver,
    ) -> Evaluation:
        spans = _tool_spans(trace)
        names = tuple(span.name for span in spans)
        method = MethodRef(
            implementation_id="contains_all",
            implementation_version="1",
        )
        operator = resolve_operator(
            method.implementation_id,
            method.implementation_version,
        )
        checks: list[CheckDraft] = []
        for expectation in _tool_call_expectations(turn, "required"):
            matching = tuple(span for span in spans if span.name == expectation.tool)
            comparison = operator(names, (expectation.tool,))
            checks.append(
                CheckDraft(
                    name=expectation.name or f"必需工具：{expectation.tool}",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if comparison.passed else Outcome.FAIL,
                    score=1.0 if comparison.passed else 0.0,
                    reason=(
                        f"已调用 {expectation.tool}"
                        if comparison.passed
                        else f"缺少必需工具：{expectation.tool}"
                    ),
                    expected=expectation.tool,
                    actual=names,
                    methods=(method,),
                    span_ids=tuple(span.span_id for span in matching),
                    failure=(
                        None
                        if comparison.passed
                        else FailureCandidate(
                            stage=FailureStage.TOOL_SELECTION,
                            at_trace_completion=True,
                        )
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))


class ForbiddenToolEvaluator:
    """Evaluate forbidden Tool calls for one Case turn."""

    kind = EvaluatorKind.RULE
    implementation_id = "forbidden_tool"
    implementation_version = "1"

    def applies_to(self, _spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return bool(_tool_call_expectations(turn, "forbidden"))

    def evaluate(
        self,
        _spec: EvaluatorSpec,
        turn: CaseTurn,
        trace: Trace,
        _resolve: ResultResolver,
    ) -> Evaluation:
        spans = _tool_spans(trace)
        names = tuple(span.name for span in spans)
        method = MethodRef(
            implementation_id="contains_none",
            implementation_version="1",
        )
        operator = resolve_operator(
            method.implementation_id,
            method.implementation_version,
        )
        checks: list[CheckDraft] = []
        for expectation in _tool_call_expectations(turn, "forbidden"):
            violating = next(
                (span for span in spans if span.name == expectation.tool),
                None,
            )
            comparison = operator(names, (expectation.tool,))
            checks.append(
                CheckDraft(
                    name=expectation.name or f"禁用工具：{expectation.tool}",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if comparison.passed else Outcome.FAIL,
                    score=1.0 if comparison.passed else 0.0,
                    reason=(
                        f"未调用 {expectation.tool}"
                        if comparison.passed
                        else f"调用了禁用工具：{expectation.tool}"
                    ),
                    expected={"absent_tool": expectation.tool},
                    actual=names,
                    methods=(method,),
                    span_ids=(violating.span_id,) if violating else (),
                    failure=(
                        None
                        if comparison.passed
                        else FailureCandidate(
                            stage=FailureStage.TOOL_SELECTION,
                            span_id=violating.span_id,
                        )
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))


class ToolArgumentsEvaluator:
    """Evaluate declared argument expectations for selected Tool calls."""

    kind = EvaluatorKind.RULE
    implementation_id = "tool_arguments"
    implementation_version = "1"

    def applies_to(self, _spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return any(
            isinstance(expectation, ToolArgumentExpectation)
            for expectation in turn.expectations
        )

    def evaluate(
        self,
        _spec: EvaluatorSpec,
        turn: CaseTurn,
        trace: Trace,
        _resolve: ResultResolver,
    ) -> Evaluation:
        checks: list[CheckDraft] = []
        for expectation in turn.expectations:
            if not isinstance(expectation, ToolArgumentExpectation):
                continue

            observation = observe_expectation(trace, expectation)
            method, operator = resolve_condition_operator(expectation.condition)
            expected = expectation.condition.model_dump(mode="python")
            name = expectation.name or f"{expectation.tool}.{expectation.path}"
            if not observation.values:
                checks.append(
                    CheckDraft(
                        name=name,
                        expectation_id=expectation.id,
                        outcome=Outcome.NOT_APPLICABLE,
                        score=None,
                        reason=f"{expectation.tool} 未调用；参数检查不适用",
                        expected=expected,
                        actual=None,
                        actual_missing=True,
                        methods=(method,),
                    )
                )
                continue

            comparisons = tuple(
                operator(value, expectation.condition)
                for value in observation.values
            )
            passed = (
                all(comparison.passed for comparison in comparisons)
                if expectation.occurrence == "all"
                else any(comparison.passed for comparison in comparisons)
            )
            failure_index = (
                next(
                    index
                    for index, comparison in enumerate(comparisons)
                    if not comparison.passed
                )
                if not passed
                else None
            )
            failure_span_id = (
                observation.span_ids[failure_index]
                if failure_index is not None
                else None
            )
            values = tuple(
                None if value is MISSING else value
                for value in observation.values
            )
            single_value = len(values) == 1
            actual = values[0] if single_value else values
            actual_missing = single_value and observation.values[0] is MISSING
            checks.append(
                CheckDraft(
                    name=name,
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if passed else Outcome.FAIL,
                    score=1.0 if passed else 0.0,
                    reason=(
                        "工具参数符合预期"
                        if passed
                        else comparisons[failure_index].reason
                    ),
                    expected=expected,
                    actual=actual,
                    actual_missing=actual_missing,
                    methods=(method,),
                    span_ids=tuple(
                        span_id
                        for span_id in observation.span_ids
                        if span_id is not None
                    ),
                    failure=(
                        None
                        if passed
                        else FailureCandidate(
                            stage=FailureStage.TOOL_ARGUMENTS,
                            span_id=failure_span_id,
                            at_trace_completion=failure_span_id is None,
                        )
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))
