"""Routing-dimension Rule evaluator."""

from __future__ import annotations

from agentgate.domain import (
    FailureStage,
    EvaluatorKind,
    MethodRef,
    Outcome,
    SkillRouteExpectation,
)

from ..base import Evaluator
from ..models import CheckDraft, Evaluation, FailureCandidate
from ..observations import condition_operator
from ..registry import register_evaluator, resolve_operator


@register_evaluator
class SkillRoutingEvaluator(Evaluator):
    kind = EvaluatorKind.RULE
    implementation_id = "skill_routing"

    def applies_to(self, spec, turn) -> bool:
        return any(
            isinstance(item, SkillRouteExpectation) for item in turn.expectations
        )

    def evaluate(self, spec, turn, trace, resolve) -> Evaluation:
        expectations = tuple(
            item
            for item in turn.expectations
            if isinstance(item, SkillRouteExpectation)
        )
        span = next((item for item in trace.spans if item.operation_type == "routing"), None)
        checks = []
        for expectation in expectations:
            operator_name = condition_operator(expectation.condition)
            method = MethodRef(
                implementation_id=operator_name,
                implementation_version="1",
            )
            if span is None:
                checks.append(
                    CheckDraft(
                        name=expectation.name or "技能路由",
                        expectation_id=expectation.id,
                        outcome=Outcome.FAIL,
                        score=0.0,
                        reason="未产生路由决策",
                        expected=expectation.condition.model_dump(mode="json"),
                        actual=None,
                        actual_missing=True,
                        methods=(method,),
                        failure=FailureCandidate(
                            stage=FailureStage.ROUTING, at_trace_completion=True
                        ),
                    )
                )
                continue

            selected = span.attributes.get("selected_skill")
            comparison = resolve_operator(operator_name, "1")(
                selected, expectation.condition
            )
            checks.append(
                CheckDraft(
                    name=expectation.name or "技能路由",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if comparison.passed else Outcome.FAIL,
                    score=1.0 if comparison.passed else 0.0,
                    reason="路由正确" if comparison.passed else comparison.reason,
                    expected=expectation.condition.model_dump(mode="json"),
                    actual=selected,
                    methods=(method,),
                    span_ids=(span.span_id,),
                    failure=None
                    if comparison.passed
                    else FailureCandidate(
                        stage=FailureStage.ROUTING, span_id=span.span_id
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))
