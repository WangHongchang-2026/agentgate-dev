"""Deterministic skill-routing evaluation."""

from __future__ import annotations

from agentgate.domain import (
    CaseTurn,
    EvaluatorKind,
    EvaluatorSpec,
    FailureStage,
    Outcome,
    SkillRouteExpectation,
    Trace,
    TraceSpan,
)

from ..models import CheckDraft, Evaluation, FailureCandidate, ResultResolver
from .observations import MISSING, value_at_path
from .operators import resolve_condition_operator


def _routing_span(trace: Trace) -> TraceSpan | None:
    return min(
        (span for span in trace.spans if span.operation_type == "routing"),
        key=lambda span: span.sequence,
        default=None,
    )


class SkillRoutingEvaluator:
    """Evaluate declared skill-routing expectations for one Case turn."""

    kind = EvaluatorKind.RULE
    implementation_id = "skill_routing"
    implementation_version = "1"

    def applies_to(self, _spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return any(
            isinstance(expectation, SkillRouteExpectation)
            for expectation in turn.expectations
        )

    def evaluate(
        self,
        _spec: EvaluatorSpec,
        turn: CaseTurn,
        trace: Trace,
        _resolve: ResultResolver,
    ) -> Evaluation:
        span = _routing_span(trace)
        checks: list[CheckDraft] = []
        for expectation in turn.expectations:
            if not isinstance(expectation, SkillRouteExpectation):
                continue

            method, operator = resolve_condition_operator(expectation.condition)
            expected = expectation.condition.model_dump(mode="python")
            if span is None:
                checks.append(
                    CheckDraft(
                        name=expectation.name or "技能路由",
                        expectation_id=expectation.id,
                        outcome=Outcome.FAIL,
                        score=0.0,
                        reason="未产生路由决策",
                        expected=expected,
                        actual=None,
                        actual_missing=True,
                        methods=(method,),
                        failure=FailureCandidate(
                            stage=FailureStage.ROUTING,
                            at_trace_completion=True,
                        ),
                    )
                )
                continue

            selected = value_at_path(span.attributes, "selected_skill")
            comparison = operator(selected, expectation.condition)
            checks.append(
                CheckDraft(
                    name=expectation.name or "技能路由",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if comparison.passed else Outcome.FAIL,
                    score=1.0 if comparison.passed else 0.0,
                    reason="路由正确" if comparison.passed else comparison.reason,
                    expected=expected,
                    actual=None if selected is MISSING else selected,
                    actual_missing=selected is MISSING,
                    methods=(method,),
                    span_ids=(span.span_id,),
                    failure=(
                        None
                        if comparison.passed
                        else FailureCandidate(
                            stage=FailureStage.ROUTING,
                            span_id=span.span_id,
                        )
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))
