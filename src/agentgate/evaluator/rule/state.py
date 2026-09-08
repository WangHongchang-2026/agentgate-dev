"""Deterministic final-state evaluation."""

from __future__ import annotations

from agentgate.domain import (
    CaseTurn,
    EvaluatorKind,
    EvaluatorSpec,
    FailureStage,
    Outcome,
    StateExpectation,
    Trace,
)

from ..models import CheckDraft, Evaluation, FailureCandidate, ResultResolver
from .observations import MISSING, observe_expectation
from .operators import resolve_condition_operator


class FinalStateEvaluator:
    """Evaluate declared state expectations for one Case turn."""

    kind = EvaluatorKind.RULE
    implementation_id = "final_state"
    implementation_version = "1"

    def applies_to(self, _spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return any(
            isinstance(expectation, StateExpectation)
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
            if not isinstance(expectation, StateExpectation):
                continue

            observation = observe_expectation(trace, expectation)
            (actual,) = observation.values
            (span_id,) = observation.span_ids
            method, operator = resolve_condition_operator(expectation.condition)
            comparison = operator(actual, expectation.condition)
            checks.append(
                CheckDraft(
                    name=expectation.name or f"最终状态：{expectation.path}",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if comparison.passed else Outcome.FAIL,
                    score=1.0 if comparison.passed else 0.0,
                    reason=(
                        f"{expectation.path} 符合预期"
                        if comparison.passed
                        else comparison.reason
                    ),
                    expected=expectation.condition.model_dump(mode="python"),
                    actual=None if actual is MISSING else actual,
                    actual_missing=actual is MISSING,
                    methods=(method,),
                    span_ids=(span_id,) if span_id else (),
                    failure=(
                        None
                        if comparison.passed
                        else FailureCandidate(
                            stage=FailureStage.FINAL_STATE,
                            span_id=span_id,
                            at_trace_completion=span_id is None,
                        )
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))
