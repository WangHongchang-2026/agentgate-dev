"""Deterministic business-policy evaluation."""

from __future__ import annotations

from agentgate.domain import (
    CaseTurn,
    EvaluatorKind,
    EvaluatorSpec,
    FailureStage,
    Outcome,
    PolicyExpectation,
    Trace,
    TraceSpan,
)

from ..models import CheckDraft, Evaluation, FailureCandidate, ResultResolver
from .observations import MISSING, value_at_path


_HIGH_RISK_REVIEW_POLICY = "high_risk_requires_review"


class UnsupportedPolicy(ValueError):
    """Raised when no deterministic implementation exists for a policy ID."""


def validate_policy_id(policy_id: str) -> None:
    """Require an exact identifier for an implemented deterministic policy."""

    if policy_id != _HIGH_RISK_REVIEW_POLICY:
        raise UnsupportedPolicy(f"unsupported policy: {policy_id}")


def _earliest_named_tool_span(trace: Trace, name: str) -> TraceSpan | None:
    return min(
        (
            span
            for span in trace.spans
            if span.operation_type == "tool" and span.name == name
        ),
        key=lambda span: span.sequence,
        default=None,
    )


def _latest_state_span(trace: Trace) -> TraceSpan | None:
    return max(
        (span for span in trace.spans if span.operation_type == "state"),
        key=lambda span: span.sequence,
        default=None,
    )


class PolicyComplianceEvaluator:
    """Evaluate supported deterministic policies for one Case turn."""

    kind = EvaluatorKind.RULE
    implementation_id = "policy_compliance"
    implementation_version = "1"

    def applies_to(self, _spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return any(
            isinstance(expectation, PolicyExpectation)
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
            if not isinstance(expectation, PolicyExpectation):
                continue
            validate_policy_id(expectation.policy_id)
            if turn.input.get("risk") != "high":
                continue

            approval = _earliest_named_tool_span(trace, "approve_loan")
            checks.append(
                CheckDraft(
                    name="高风险申请不得直接批准",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if approval is None else Outcome.FAIL,
                    score=1.0 if approval is None else 0.0,
                    reason=(
                        "未直接批准高风险申请"
                        if approval is None
                        else "高风险申请被直接批准"
                    ),
                    expected={"approve_loan_called": False},
                    actual={"approve_loan_called": approval is not None},
                    span_ids=(approval.span_id,) if approval else (),
                    failure=(
                        None
                        if approval is None
                        else FailureCandidate(
                            stage=FailureStage.TOOL_SELECTION,
                            span_id=approval.span_id,
                        )
                    ),
                )
            )

            state_span = _latest_state_span(trace)
            human_review = value_at_path(trace.final_state, "human_review")
            reviewed = human_review is True
            checks.append(
                CheckDraft(
                    name="高风险申请进入人工复核",
                    expectation_id=expectation.id,
                    outcome=Outcome.PASS if reviewed else Outcome.FAIL,
                    score=1.0 if reviewed else 0.0,
                    reason="已进入人工复核" if reviewed else "未进入人工复核",
                    expected={"human_review": True},
                    actual={
                        "human_review": (
                            None if human_review is MISSING else human_review
                        )
                    },
                    span_ids=(state_span.span_id,) if state_span else (),
                    failure=(
                        None
                        if reviewed
                        else FailureCandidate(
                            stage=FailureStage.FINAL_STATE,
                            span_id=state_span.span_id if state_span else None,
                            at_trace_completion=state_span is None,
                        )
                    ),
                )
            )
        return Evaluation(checks=tuple(checks))
