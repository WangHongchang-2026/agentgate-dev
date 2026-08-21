from agentgate.control_plane import EvaluationService
from agentgate.domain import (
    Dimension, FailureStage, Outcome, RuleEvaluatorSpec, SpanKind, Trace, TraceSpan,
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
    assert by_id["policy-compliance"].primary_failure_step == FailureStage.TOOL_SELECTION
    assert len(by_id["policy-compliance"].checks) == 2
    assert any(item.outcome == Outcome.FAIL for item in by_id["policy-compliance"].checks)
    assert all(item.turn_id == "high-risk-turn-1" for item in by_id["final-state"].checks)
    assert by_id["final-state"].checks[0].expected["kind"] == "equals"


def test_primary_failure_uses_trace_sequence_not_enum_order():
    trace = Trace(
        run_id="run",
        case_id="case",
        spans=(
            TraceSpan(id="routing", trace_id="trace", name="route",
                      kind=SpanKind.ROUTING, sequence=5),
            TraceSpan(id="state", trace_id="trace", name="state",
                      kind=SpanKind.STATE, sequence=1),
        ),
    )
    spec = RuleEvaluatorSpec(
        id="ordered", name="ordered", evaluator_type="final_state",
        dimension=Dimension.STATE, metric="ordered",
    )
    evaluation = Evaluation(checks=(
        CheckDraft(
            name="routing", outcome=Outcome.FAIL, score=0, reason="routing",
            failure=FailureCandidate(stage=FailureStage.ROUTING, span_id="routing"),
        ),
        CheckDraft(
            name="state", outcome=Outcome.FAIL, score=0, reason="state",
            failure=FailureCandidate(stage=FailureStage.FINAL_STATE, span_id="state"),
        ),
    ))
    result = calculate_result(spec, "run", "case", trace, evaluation)
    assert result.primary_failure_step == FailureStage.FINAL_STATE
