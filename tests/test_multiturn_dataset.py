from agentgate.case import DatasetService
from agentgate.control_plane import EvaluationService
from agentgate.domain import (
    Case, CaseTurn, Equals, MatchesPattern, OutputExpectation, StateExpectation,
)
from agentgate.storage.sqlite import SQLiteRepository


def test_multi_turn_session_produces_turn_aware_trace_and_checks(tmp_path):
    repository = SQLiteRepository(tmp_path / "multi.db")
    datasets = DatasetService(repository)
    dataset = datasets.create_dataset("Multi-turn")
    datasets.create_draft(dataset.id)
    datasets.save_case(dataset.id, Case(
        id="multi-case",
        name="Collect then approve",
        turns=(
            CaseTurn(
                id="collect",
                input={"skill": "loan_approval"},
                expected_skill="loan_approval",
                expectations=(OutputExpectation(
                    id="ask-fields",
                    path="message",
                    condition=MatchesPattern(pattern="请补充"),
                ),),
            ),
            CaseTurn(
                id="decide",
                input={"application_id": "M-1", "risk": "high", "amount": 50000},
                expected_skill="loan_approval",
                expectations=(StateExpectation(
                    id="review-state",
                    path="status",
                    condition=Equals(expected="pending_review"),
                ),),
                required_tools=("credit_inquiry", "request_human_review"),
                forbidden_tools=("approve_loan",),
                policy_rules=("high_risk_requires_review",),
            ),
        ),
    ))
    version = datasets.publish_draft(dataset.id)

    service = EvaluationService(repository)
    run = service.launch(
        "loan-agent-v2-fixed", dataset.id, version.version
    )
    trace = repository.get_trace(run.id, "multi-case")
    assert [item.turn_id for item in trace.turns] == ["collect", "decide"]
    assert {span.attributes["turn_id"] for span in trace.spans} == {"collect", "decide"}
    report = service.run_detail(run.id)
    output = next(item for item in report.results if item.evaluator_id == "final-output")
    state = next(item for item in report.results if item.evaluator_id == "final-state")
    assert output.checks[0].turn_id == "collect"
    assert state.checks[0].turn_id == "decide"
    assert report.gate.outcome == "pass"
