from agentgate.application import DatasetManagement
from agentgate.domain import (
    Case, CaseTurn, Equals, MatchesPattern, OutputExpectation, PolicyExpectation,
    SkillRouteExpectation, StateExpectation, ToolCallExpectation,
)
from agentgate.storage.sqlite import SQLiteRepository


def test_multi_turn_session_produces_turn_aware_trace_and_checks(
    tmp_path, execute_demo
):
    repository = SQLiteRepository(tmp_path / "multi.db")
    datasets = DatasetManagement(repository)
    dataset = datasets.create_dataset("Multi-turn")
    datasets.create_draft(dataset.id)
    datasets.save_case(dataset.id, Case(
        id="multi-case",
        name="Collect then approve",
        turns=(
            CaseTurn(
                id="collect",
                input={"skill": "loan_approval"},
                expectations=(
                    SkillRouteExpectation(
                        id="collect-route", condition=Equals(expected="loan_approval")
                    ),
                    OutputExpectation(
                        id="ask-fields",
                        path="message",
                        condition=MatchesPattern(pattern="Please provide"),
                    ),
                ),
            ),
            CaseTurn(
                id="decide",
                input={"application_id": "M-1", "risk": "high", "amount": 50000},
                expectations=(
                    SkillRouteExpectation(
                        id="decide-route", condition=Equals(expected="loan_approval")
                    ),
                    StateExpectation(
                        id="review-state",
                        path="status",
                        condition=Equals(expected="pending_review"),
                    ),
                    ToolCallExpectation(id="credit", tool="credit_inquiry"),
                    ToolCallExpectation(id="review", tool="request_human_review"),
                    ToolCallExpectation(
                        id="no-approval", tool="approve_loan", mode="forbidden"
                    ),
                    PolicyExpectation(
                        id="policy", policy_id="high_risk_requires_review"
                    ),
                ),
            ),
        ),
    ))
    version = datasets.publish_draft(dataset.id)

    run, report = execute_demo(
        repository,
        "loan-agent-v2-fixed",
        dataset_id=dataset.id,
        dataset_version=version.version,
    )
    trace = repository.get_trace(run.id, "multi-case")
    assert list(trace.turn_outcomes) == ["collect", "decide"]
    turn_ids = {
        span.attributes["agentgate.turn.id"]
        for span in trace.spans
        if span.operation_type == "turn"
    }
    assert turn_ids == {"collect", "decide"}
    assert not any(
        span.operation_type == "tool"
        for span in trace.for_turn("collect").spans
    )
    assert {
        span.name
        for span in trace.for_turn("decide").spans
        if span.operation_type == "tool"
    } == {"credit_inquiry", "request_human_review"}
    output = next(item for item in report.results if item.evaluator_id == "final-output")
    state = next(item for item in report.results if item.evaluator_id == "final-state")
    assert output.checks[0].turn_id == "collect"
    assert state.checks[0].turn_id == "decide"
    assert report.release_gate.outcome == "pass"
