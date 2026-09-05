"""Final-output Rule evaluator."""

from __future__ import annotations

from agentgate.domain import FailureStage, EvaluatorKind, MethodRef, Outcome, OutputExpectation

from ..base import Evaluator
from ..models import CheckDraft, Evaluation, FailureCandidate
from ..observations import MISSING, condition_operator, observe
from ..registry import register_evaluator, resolve_operator


@register_evaluator
class FinalOutputEvaluator(Evaluator):
    kind = EvaluatorKind.RULE
    implementation_id = "final_output"

    def applies_to(self, spec, turn) -> bool:
        return any(isinstance(item, OutputExpectation) for item in turn.expectations)

    def evaluate(self, spec, turn, trace, resolve) -> Evaluation:
        checks = []
        for expectation in (
            item for item in turn.expectations if isinstance(item, OutputExpectation)
        ):
            observation = observe(trace, expectation)
            actual = observation.values[0]
            operator_name = condition_operator(expectation.condition)
            method = MethodRef(
                implementation_id=operator_name,
                implementation_version="1",
            )
            comparison = resolve_operator(operator_name, "1")(actual, expectation.condition)
            checks.append(CheckDraft(
                name=expectation.name or f"最终输出：{expectation.path or '完整输出'}",
                expectation_id=expectation.id,
                outcome=Outcome.PASS if comparison.passed else Outcome.FAIL,
                score=1.0 if comparison.passed else 0.0,
                reason="最终输出符合预期" if comparison.passed else comparison.reason,
                expected=expectation.condition.model_dump(mode="json"),
                actual=None if actual is MISSING else actual,
                actual_missing=actual is MISSING,
                methods=(method,),
                failure=None if comparison.passed else FailureCandidate(
                    stage=FailureStage.FINAL_OUTPUT, at_trace_completion=True
                ),
            ))
        return Evaluation(checks=tuple(checks))
