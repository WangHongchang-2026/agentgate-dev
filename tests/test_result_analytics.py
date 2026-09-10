import pytest

from agentgate.domain import RunStatus
from agentgate.result.analytics import calculate_result_analytics
from agentgate.storage.sqlite import SQLiteRepository


def _by_key(breakdown):
    return {bucket.key: bucket for bucket in breakdown.buckets}


def test_result_analytics_calculates_all_available_breakdowns(
    tmp_path, execute_demo
) -> None:
    repository = SQLiteRepository(tmp_path / "analytics.db")
    run, report = execute_demo(repository, "loan-agent-v1-risky")

    analytics = calculate_result_analytics(run, report.results)

    assert analytics.run_id == run.id
    assert len(analytics.by_evaluator.buckets) == 7
    category = _by_key(analytics.by_category)["boundary"]
    difficulty = _by_key(analytics.by_difficulty)["hard"]
    assert category.case_count == difficulty.case_count == 1
    assert category.observation_count == difficulty.observation_count == 7
    assert set(_by_key(analytics.by_tag)) == {"high-risk", "policy"}

    routing = _by_key(analytics.by_routing)["loan_approval"]
    assert routing.observation_count == 1
    assert routing.pass_rate == 1.0

    tools = _by_key(analytics.by_tool_use)
    assert set(tools) == {
        "approve_loan",
        "credit_inquiry",
        "request_human_review",
    }
    assert tools["credit_inquiry"].pass_rate == 1.0
    assert tools["approve_loan"].failure_rate == 1.0
    assert tools["request_human_review"].failure_rate == 1.0

    failures = _by_key(analytics.by_failure_type)
    assert "tool_selection" in failures
    assert all(bucket.failed > 0 for bucket in failures.values())


def test_result_analytics_marks_optional_dimensions_unavailable(
    tmp_path, execute_demo
) -> None:
    repository = SQLiteRepository(tmp_path / "analytics-optional.db")
    run, report = execute_demo(repository, "loan-agent-v2-fixed")
    final_state = tuple(
        result for result in report.results if result.evaluator_id == "final-state"
    )

    analytics = calculate_result_analytics(run, final_state)

    assert analytics.by_evaluator.available is True
    assert analytics.by_category.available is True
    assert analytics.by_difficulty.available is True
    assert analytics.by_tag.available is True
    assert analytics.by_routing.available is False
    assert analytics.by_tool_use.available is False
    assert analytics.by_failure_type.available is False
    assert analytics.by_routing.buckets == ()


def test_result_analytics_rejects_invalid_run_and_result_relationships(
    tmp_path, execute_demo
) -> None:
    repository = SQLiteRepository(tmp_path / "analytics-errors.db")
    run, report = execute_demo(repository, "loan-agent-v2-fixed")
    result = report.results[0]

    with pytest.raises(ValueError, match="completed EvaluationRun"):
        calculate_result_analytics(
            run.model_copy(update={"status": RunStatus.PENDING}),
            report.results,
        )
    with pytest.raises(ValueError, match="different Run"):
        calculate_result_analytics(
            run,
            (result.model_copy(update={"run_id": "another-run"}),),
        )
    with pytest.raises(ValueError, match="unique EvaluationResult ids"):
        calculate_result_analytics(run, (result, result))
    with pytest.raises(ValueError, match="unknown Cases"):
        calculate_result_analytics(
            run,
            (result.model_copy(update={"case_id": "unknown-case"}),),
        )
