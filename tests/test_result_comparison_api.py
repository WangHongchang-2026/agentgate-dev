from fastapi.testclient import TestClient

from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import EvaluatorKind, EvaluatorSeverity
from agentgate.server.app import create_app


class RecordingDispatcher:
    def __init__(self, fail_calls: set[int] | None = None) -> None:
        self.fail_calls = fail_calls or set()
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if len(self.run_ids) in self.fail_calls:
            raise ConnectionError("redis password=secret")


def _launch_payload() -> dict[str, object]:
    return {
        "baseline_version": "loan-agent-v1-risky",
        "candidate_version": "loan-agent-v2-fixed",
        "dataset_id": LOAN_DATASET.id,
        "dataset_version": 1,
        "evaluators": [
            {"id": "skill-routing", "version": "1"},
            {"id": "final-state", "version": "1"},
        ],
    }


def test_launch_run_comparison_creates_and_dispatches_controlled_pair(
    tmp_path,
) -> None:
    dispatcher = RecordingDispatcher()
    application = create_app(tmp_path / "comparison-launch.db", dispatcher)

    with TestClient(application) as client:
        response = client.post("/api/run-comparisons", json=_launch_payload())

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"baseline", "candidate"}
    assert set(body["baseline"]) == {"run_id", "status"}
    assert set(body["candidate"]) == {"run_id", "status"}
    assert body["baseline"]["status"] == "pending"
    assert body["candidate"]["status"] == "pending"
    assert dispatcher.run_ids == [
        body["baseline"]["run_id"],
        body["candidate"]["run_id"],
    ]

    repository = application.state.dependencies.repository
    baseline = repository.get_run(body["baseline"]["run_id"])
    candidate = repository.get_run(body["candidate"]["run_id"])
    assert baseline is not None
    assert candidate is not None
    assert baseline.manifest.dataset == candidate.manifest.dataset
    assert baseline.manifest.evaluator_specs == candidate.manifest.evaluator_specs


def test_launch_run_comparison_selects_exact_historical_evaluator_version(
    tmp_path,
) -> None:
    dispatcher = RecordingDispatcher()
    application = create_app(tmp_path / "comparison-exact-evaluator.db", dispatcher)
    evaluators = application.state.dependencies.evaluators
    evaluator, _ = evaluators.create_evaluator(
        "Versioned comparison output",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="comparison_output_v1",
        implementation_id="final_output",
        config={},
    )
    first = evaluators.publish_draft(evaluator.id)
    evaluators.update_evaluator(evaluator.id, enabled=True)
    evaluators.create_draft(evaluator.id)
    evaluators.replace_draft(
        evaluator.id,
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="comparison_output_v2",
        severity=EvaluatorSeverity.BLOCKING,
        implementation_id="final_output",
        implementation_version="1",
        config={},
        children=(),
        combination=None,
    )
    second = evaluators.publish_draft(evaluator.id)
    payload = _launch_payload()
    payload["evaluators"] = [{"id": evaluator.id, "version": first.version}]

    with TestClient(application) as client:
        response = client.post("/api/run-comparisons", json=payload)

    assert response.status_code == 202
    assert second.version == "2"
    baseline = application.state.dependencies.repository.get_run(
        response.json()["baseline"]["run_id"]
    )
    candidate = application.state.dependencies.repository.get_run(
        response.json()["candidate"]["run_id"]
    )
    assert baseline is not None
    assert candidate is not None
    assert baseline.manifest.evaluator_specs == (first,)
    assert candidate.manifest.evaluator_specs == (first,)


def test_launch_run_comparison_rejects_unknown_evaluator_version(tmp_path) -> None:
    application = create_app(tmp_path / "comparison-unknown-evaluator.db")
    payload = _launch_payload()
    payload["evaluators"] = [{"id": "final-state", "version": "999"}]

    with TestClient(application) as client:
        response = client.post("/api/run-comparisons", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "unknown Evaluator version: final-state@999"
    )
    assert application.state.dependencies.repository.list_runs() == []


def test_launch_run_comparison_rejects_identical_versions(tmp_path) -> None:
    dispatcher = RecordingDispatcher()
    application = create_app(tmp_path / "comparison-same-version.db", dispatcher)
    payload = _launch_payload()
    payload["candidate_version"] = payload["baseline_version"]

    with TestClient(application) as client:
        response = client.post("/api/run-comparisons", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "A/B variants must use different Agent versions"
    )
    assert dispatcher.run_ids == []
    assert application.state.dependencies.repository.list_runs() == []


def test_launch_run_comparison_rejects_unknown_demo_version(tmp_path) -> None:
    dispatcher = RecordingDispatcher()
    application = create_app(tmp_path / "comparison-unknown-version.db", dispatcher)
    payload = _launch_payload()
    payload["candidate_version"] = "unknown-version"

    with TestClient(application) as client:
        response = client.post("/api/run-comparisons", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "unknown demo Target version: unknown-version"
    )
    assert dispatcher.run_ids == []
    assert application.state.dependencies.repository.list_runs() == []


def test_launch_run_comparison_rejects_raw_target_configuration(tmp_path) -> None:
    dispatcher = RecordingDispatcher()
    application = create_app(tmp_path / "comparison-extra-input.db", dispatcher)
    payload = _launch_payload()
    payload["invocation_config"] = {"api_key": "must-not-be-accepted"}

    with TestClient(application) as client:
        response = client.post("/api/run-comparisons", json=payload)

    assert response.status_code == 422
    assert dispatcher.run_ids == []
    assert application.state.dependencies.repository.list_runs() == []


def test_launch_run_comparison_returns_partial_dispatch_states(tmp_path) -> None:
    dispatcher = RecordingDispatcher(fail_calls={1})
    application = create_app(tmp_path / "comparison-partial-dispatch.db", dispatcher)

    with TestClient(application) as client:
        response = client.post("/api/run-comparisons", json=_launch_payload())

    assert response.status_code == 202
    body = response.json()
    assert dispatcher.run_ids == [
        body["baseline"]["run_id"],
        body["candidate"]["run_id"],
    ]
    assert body["baseline"]["status"] == "failed"
    assert body["candidate"]["status"] == "pending"
    assert "secret" not in response.text

    repository = application.state.dependencies.repository
    baseline = repository.get_run(body["baseline"]["run_id"])
    candidate = repository.get_run(body["candidate"]["run_id"])
    assert baseline is not None
    assert candidate is not None
    assert baseline.error == "Run dispatch failed: ConnectionError"
    assert candidate.error is None


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
