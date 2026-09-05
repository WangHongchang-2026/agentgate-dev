import pytest
from pydantic import ValidationError

from agentgate.domain import (
    CheckResult,
    EvaluationResult,
    EvaluatorErrorDetail,
    EvaluatorKind,
    EvaluatorSeverity,
    FailureStage,
    JudgeRecord,
    MethodRef,
    Outcome,
)


TRACE_ID = "a" * 32
SPAN_ID = "b" * 16
EVALUATOR_HASH = "c" * 64


def check(outcome: Outcome = Outcome.PASS, **changes) -> CheckResult:
    values = {
        "name": "state check",
        "outcome": outcome,
        "score": None if outcome == Outcome.NOT_APPLICABLE else 1.0,
        "reason": "checked",
    }
    if outcome == Outcome.FAIL:
        values.update({
            "score": 0.0,
            "span_ids": (SPAN_ID,),
            "failure_stage": FailureStage.FINAL_STATE,
            "failure_sequence": 3,
            "failure_span_id": SPAN_ID,
        })
    values.update(changes)
    return CheckResult(**values)


def result(outcome: Outcome = Outcome.PASS, **changes) -> EvaluationResult:
    checks = {
        Outcome.PASS: (check(),),
        Outcome.FAIL: (check(Outcome.FAIL),),
        Outcome.REVIEW: (check(Outcome.REVIEW, score=0.5),),
        Outcome.NOT_APPLICABLE: (check(Outcome.NOT_APPLICABLE),),
        Outcome.ERROR: (),
    }[outcome]
    values = {
        "run_id": "run",
        "case_id": "case",
        "trace_id": TRACE_ID,
        "evaluator_id": "state",
        "evaluator_name": "State",
        "evaluator_version": "1",
        "evaluator_content_sha256": EVALUATOR_HASH,
        "evaluator_kind": EvaluatorKind.RULE,
        "dimension": "state",
        "metric": "state_match",
        "severity": EvaluatorSeverity.STANDARD,
        "outcome": outcome,
        "score": None if outcome in (Outcome.NOT_APPLICABLE, Outcome.ERROR) else 1.0,
        "reason": "evaluated",
        "checks": checks,
        "primary_failure_stage": FailureStage.FINAL_STATE if outcome == Outcome.FAIL else None,
        "error_detail": EvaluatorErrorDetail(
            category="timeout",
            exception_type="TimeoutError",
            message="timed out",
            retryable=True,
        ) if outcome == Outcome.ERROR else None,
    }
    values.update(changes)
    return EvaluationResult(**values)


def test_method_and_judge_records_have_explicit_provenance():
    method = MethodRef(implementation_id="equals", implementation_version="1")
    judge = JudgeRecord(
        provider_id="private-openai-compatible",
        requested_model="judge-default",
        resolved_model="model-v2",
        request_sha256="d" * 64,
        raw_response='{"score": 1}',
        input_tokens=20,
        output_tokens=5,
        latency_ms=12.5,
    )
    value = result(
        evaluator_kind=EvaluatorKind.LLM_JUDGE,
        checks=(check(methods=(method,)),),
        judge_record=judge,
    )
    assert value.checks[0].methods[0].implementation_id == "equals"
    assert value.judge_record.request_sha256 == "d" * 64


def test_failed_check_requires_location_and_failure_span_evidence():
    with pytest.raises(ValidationError, match="failure_stage and failure_sequence"):
        check(Outcome.FAIL, failure_stage=None, failure_sequence=None)
    with pytest.raises(ValidationError, match="included in span_ids"):
        check(Outcome.FAIL, span_ids=())
    with pytest.raises(ValidationError, match="only failed checks"):
        check(failure_stage=FailureStage.FINAL_STATE, failure_sequence=1)


def test_result_outcome_must_match_checks_and_error_detail():
    with pytest.raises(ValidationError, match="failed results require"):
        result(Outcome.FAIL, checks=(check(),))
    with pytest.raises(ValidationError, match="earliest failed check"):
        result(Outcome.FAIL, primary_failure_stage=FailureStage.ROUTING)
    with pytest.raises(ValidationError, match="error results require"):
        result(Outcome.ERROR, error_detail=None)
    with pytest.raises(ValidationError, match="only error results"):
        result(error_detail=EvaluatorErrorDetail(
            category="crash", exception_type="RuntimeError", message="failed"
        ))


def test_judge_record_is_required_only_for_measured_llm_judge_results():
    with pytest.raises(ValidationError, match="require judge_record"):
        result(evaluator_kind=EvaluatorKind.LLM_JUDGE)
    with pytest.raises(ValidationError, match="only LLM Judge results"):
        result(judge_record=JudgeRecord(
            provider_id="provider",
            requested_model="model",
            request_sha256="d" * 64,
            raw_response="ok",
        ))


def test_error_category_and_hybrid_judge_record_are_restricted():
    with pytest.raises(ValidationError, match="Input should be"):
        EvaluatorErrorDetail(
            category="typo", exception_type="RuntimeError", message="failed"
        )
    with pytest.raises(ValidationError, match="only LLM Judge results"):
        result(
            evaluator_kind=EvaluatorKind.HYBRID,
            judge_record=JudgeRecord(
                provider_id="provider",
                requested_model="model",
                request_sha256="d" * 64,
                raw_response="ok",
            ),
        )


def test_result_rejects_invalid_trace_and_evaluator_hashes():
    with pytest.raises(ValidationError, match="trace_id"):
        result(trace_id="not-otel")
    with pytest.raises(ValidationError, match="evaluator_content_sha256"):
        result(evaluator_content_sha256="not-sha256")

