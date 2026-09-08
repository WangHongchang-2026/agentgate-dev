"""Deterministic final-output evaluation."""

from __future__ import annotations

from agentgate.domain import (
    CaseTurn,
    EvaluatorKind,
    EvaluatorSpec,
    FailureStage,
    Outcome,
    OutputExpectation,
    Trace,
)

from ..models import CheckDraft, Evaluation, FailureCandidate, ResultResolver
from .observations import MISSING, observe_expectation
from .operators import resolve_condition_operator


class FinalOutputEvaluator:
    """Evaluate declared output expectations for one Case turn."""

    kind = EvaluatorKind.RULE
    implementation_id = "final_output"
    implementation_version = "1"

    def applies_to(self, _spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return any(
            isinstance(expectation, OutputExpectation)
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
            if not isinstance(expectation, OutputExpectation):
                continue

            observation = observe_expectation(trace, expectation)
            actual = observation.values[0]
            method, operator = resolve_condition_operator(expectation.condition)
            comparison = operator(actual, expectation.condition)
            checks.append(
                CheckDraft(
                    name=expectation.name
                    or f"最终输出：{expectation.path or '完整输出'}",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if comparison.passed else Outcome.FAIL,
                    score=1.0 if comparison.passed else 0.0,
                    reason=(
                        "最终输出符合预期"
                        if comparison.passed
                        else comparison.reason
                    ),
                    expected=expectation.condition.model_dump(mode="python"),
                    actual=None if actual is MISSING else actual,
                    actual_missing=actual is MISSING,
                    methods=(method,),
                    failure=(
                        None
                        if comparison.passed
                        else FailureCandidate(
                            stage=FailureStage.FINAL_OUTPUT,
                            at_trace_completion=True,
                        )
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))
