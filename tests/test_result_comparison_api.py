from fastapi.testclient import TestClient

from agentgate.server.app import create_app


class RecordingDispatcher:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)


def test_compare_completed_runs(tmp_path) -> None:
    application = create_app(tmp_path / "comparison-api.db")
    dependencies = application.state.dependencies
    baseline = dependencies.execute_demo_run("loan-agent-v1-risky")
    candidate = dependencies.execute_demo_run("loan-agent-v2-fixed")

    with TestClient(application) as client:
        response = client.get(
            "/api/run-comparisons",
            params={
                "baseline_run_id": baseline.id,
                "candidate_run_id": candidate.id,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["baseline_run_id"] == baseline.id
    assert body["candidate_run_id"] == candidate.id
    assert body["baseline_target_version"] == "loan-agent-v1-risky"
    assert body["candidate_target_version"] == "loan-agent-v2-fixed"
    assert body["overall_score_delta"] > 0
    assert any(item["change"] == "improvement" for item in body["case_deltas"])


def test_unknown_comparison_run_returns_not_found(tmp_path) -> None:
    application = create_app(tmp_path / "comparison-missing.db")

    with TestClient(application) as client:
        response = client.get(
            "/api/run-comparisons",
            params={
                "baseline_run_id": "missing-baseline",
                "candidate_run_id": "missing-candidate",
            },
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown EvaluationRun: missing-baseline"


def test_incomplete_comparison_run_returns_conflict(tmp_path) -> None:
    dispatcher = RecordingDispatcher()
    application = create_app(tmp_path / "comparison-incomplete.db", dispatcher)
    dependencies = application.state.dependencies
    baseline = dependencies.execute_demo_run("loan-agent-v1-risky")
    candidate = dependencies.submit_demo_run("loan-agent-v2-fixed")

    with TestClient(application) as client:
        response = client.get(
            "/api/run-comparisons",
            params={
                "baseline_run_id": baseline.id,
                "candidate_run_id": candidate.id,
            },
        )

    assert response.status_code == 409
    assert dispatcher.run_ids == [candidate.id]
    assert response.json()["detail"] == (
        "EvaluationReport requires a completed EvaluationRun"
    )


def test_incompatible_comparison_runs_return_conflict(tmp_path) -> None:
    application = create_app(tmp_path / "comparison-incompatible.db")
    dependencies = application.state.dependencies
    baseline = dependencies.execute_demo_run(
        "loan-agent-v1-risky",
        evaluator_ids=["skill-routing"],
    )
    candidate = dependencies.execute_demo_run(
        "loan-agent-v2-fixed",
        evaluator_ids=["final-state"],
    )

    with TestClient(application) as client:
        response = client.get(
            "/api/run-comparisons",
            params={
                "baseline_run_id": baseline.id,
                "candidate_run_id": candidate.id,
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "reports use different primary Evaluators"
