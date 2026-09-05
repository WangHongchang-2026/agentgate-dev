from agentgate.control_plane import EvaluationService
from agentgate.domain import (
    FailureStage, Outcome, EvaluatorSpec, Trace, TraceSpan,
)
from agentgate.evaluator.calc_score import calculate_result
from agentgate.evaluator.models import CheckDraft, Evaluation, FailureCandidate
from agentgate.storage.sqlite import SQLiteRepository


def test_seven_rules_keep_details_and_trace_ordered_primary_failure(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "rules.db"))
    run = service.launch("loan-agent-v1-risky")
    report = service.run_detail(run.id)
    assert len(report.results) == 7
    by_id = {item.evaluator_id: item for item in report.results}
    assert by_id["skill-routing"].outcome == Outcome.PASS
    assert by_id["tool-arguments"].outcome == Outcome.NOT_APPLICABLE
    assert by_id["final-output"].outcome == Outcome.NOT_APPLICABLE
    assert by_id["policy-compliance"].primary_failure_stage == FailureStage.TOOL_SELECTION
    assert len(by_id["policy-compliance"].checks) == 2
    assert any(item.outcome == Outcome.FAIL for item in by_id["policy-compliance"].checks)
    assert all(item.turn_id == "high-risk-turn-1" for item in by_id["final-state"].checks)
    assert by_id["final-state"].checks[0].expected["kind"] == "equals"


def test_primary_failure_uses_trace_sequence_not_enum_order():
    trace = Trace(
        trace_id="0" * 32,
        run_id="run",
        case_id="case",
        spans=(
            TraceSpan(span_id="1" * 16, trace_id="0" * 32, name="route",
                      operation_type="routing", sequence=5),
            TraceSpan(span_id="2" * 16, trace_id="0" * 32, name="state",
                      operation_type="state", sequence=1),
        ),
    )
    spec = EvaluatorSpec(
        id="ordered", name="ordered", implementation_id="final_state",
        dimension="state", metric="ordered",
    )
    evaluation = Evaluation(checks=(
        CheckDraft(
            name="routing", outcome=Outcome.FAIL, score=0, reason="routing",
            failure=FailureCandidate(stage=FailureStage.ROUTING, span_id="1" * 16),
        ),
        CheckDraft(
            name="state", outcome=Outcome.FAIL, score=0, reason="state",
            failure=FailureCandidate(stage=FailureStage.FINAL_STATE, span_id="2" * 16),
        ),
    ))
    result = calculate_result(spec, "run", "case", trace, evaluation)
    assert result.primary_failure_stage == FailureStage.FINAL_STATE
