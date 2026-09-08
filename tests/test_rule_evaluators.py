from agentgate.domain import FailureStage, Outcome
from agentgate.storage.sqlite import SQLiteRepository


def test_seven_rules_keep_details_and_trace_ordered_primary_failure(
    tmp_path, execute_demo
):
    _, report = execute_demo(
        SQLiteRepository(tmp_path / "rules.db"), "loan-agent-v1-risky"
    )
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
