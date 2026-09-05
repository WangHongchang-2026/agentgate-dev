"""Final-state Rule evaluator."""

from __future__ import annotations

from agentgate.domain import FailureStage, EvaluatorKind, MethodRef, Outcome, StateExpectation

from ..base import Evaluator
from ..models import CheckDraft, Evaluation, FailureCandidate
from ..observations import MISSING, condition_operator, observe
from ..registry import register_evaluator, resolve_operator


@register_evaluator
class FinalStateEvaluator(Evaluator):
    kind = EvaluatorKind.RULE
    implementation_id = "final_state"

    def applies_to(self, spec, turn) -> bool:
        return any(isinstance(item, StateExpectation) for item in turn.expectations)

    def evaluate(self, spec, turn, trace, resolve) -> Evaluation:
        checks = []
        for expectation in (
            item for item in turn.expectations if isinstance(item, StateExpectation)
        ):
            observation = observe(trace, expectation)
            actual = observation.values[0]
            operator_name = condition_operator(expectation.condition)
            method = MethodRef(
                implementation_id=operator_name,
                implementation_version="1",
            )
            outcome = resolve_operator(operator_name, "1")(actual, expectation.condition)
            span_id = observation.span_ids[0] if observation.span_ids else None
            checks.append(CheckDraft(
                name=expectation.name or f"最终状态：{expectation.path}",
                expectation_id=expectation.id,
                outcome=Outcome.PASS if outcome.passed else Outcome.FAIL,
                score=1.0 if outcome.passed else 0.0,
                reason=f"{expectation.path} 符合预期" if outcome.passed else outcome.reason,
                expected=expectation.condition.model_dump(mode="json"),
                actual=None if actual is MISSING else actual,
                actual_missing=actual is MISSING,
                methods=(method,),
                span_ids=(span_id,) if span_id else (),
                failure=None if outcome.passed else FailureCandidate(
                    stage=FailureStage.FINAL_STATE,
                    span_id=span_id,
                    at_trace_completion=span_id is None,
                ),
            ))
        return Evaluation(checks=tuple(checks))
