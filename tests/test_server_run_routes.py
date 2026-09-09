from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application import SkillAnalysis
from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import (
    Case,
    CaseTurn,
    RunStatus,
    SkillAnalysisReport,
    SkillAnalysisStatus,
    TargetDescriptor,
    transition_run,
)
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.runs import router


class RecordingDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self.run_ids: list[str] = []
        self.cancelled_run_ids: list[str] = []
        self.error = error

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if self.error is not None:
            raise self.error

    def cancel(self, run_id: str) -> None:
        self.cancelled_run_ids.append(run_id)


def _client(
    tmp_path, dispatcher: RecordingDispatcher | None = None
) -> tuple[TestClient, RecordingDispatcher]:
    selected = dispatcher or RecordingDispatcher()
    app = FastAPI()
    app.state.dependencies = build_dependencies(
        tmp_path / "run-routes.db", selected
    )
    app.include_router(router)
    return TestClient(app), selected


def test_run_routes_submit_pending_evaluation_and_expose_activity(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    with client:
        assert client.get("/api/runs").json() == []

        launched = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "evaluator_ids": ["skill-routing", "final-state"],
            },
        )
        run_id = launched.json()["run_id"]
        listed = client.get("/api/runs", params={"status": "pending"})
        status = client.get(f"/api/runs/{run_id}/status")
        activity = client.get("/api/runs/activity")

    assert launched.status_code == 202
    assert launched.json()["status"] == "pending"
    assert launched.json()["completed_cases"] == 0
    assert dispatcher.run_ids == [run_id]
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [run_id]
    assert listed.json()[0]["manifest"]["timeout_seconds"] == 300
    assert listed.json()[0]["manifest"]["max_parallel_cases"] == 1
    assert listed.json()[0]["manifest"]["max_retries"] == 0
    assert status.status_code == 200
    assert status.json()["queue_position"] == 1
    assert activity.status_code == 200
    assert activity.json()["status_counts"]["pending"] == 1
    assert activity.json()["queued"][0]["run_id"] == run_id


def test_run_route_persists_configured_case_concurrency(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        launched = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "timeout_seconds": 60,
                "max_parallel_cases": 4,
            },
        )
        runs = client.get("/api/runs")

    assert launched.status_code == 202
    assert runs.json()[0]["manifest"]["timeout_seconds"] == 60
    assert runs.json()[0]["manifest"]["max_parallel_cases"] == 4
    assert dispatcher.run_ids == [launched.json()["run_id"]]


def test_run_route_rejects_unsafe_case_concurrency(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        below_minimum = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "max_parallel_cases": 0,
            },
        )
        above_maximum = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "max_parallel_cases": 33,
            },
        )
        runs = client.get("/api/runs")

    assert below_minimum.status_code == 422
    assert above_maximum.status_code == 422
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_route_rejects_unsafe_case_timeout(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        below_minimum = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "timeout_seconds": 0,
            },
        )
        above_maximum = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "timeout_seconds": 3601,
            },
        )
        runs = client.get("/api/runs")

    assert below_minimum.status_code == 422
    assert above_maximum.status_code == 422
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_route_persists_configured_retry_limit(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        launched = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "max_retries": 3,
            },
        )
        runs = client.get("/api/runs")

    assert launched.status_code == 202
    assert runs.json()[0]["manifest"]["max_retries"] == 3
    assert dispatcher.run_ids == [launched.json()["run_id"]]


def test_run_route_rejects_unsafe_retry_limit(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        below_minimum = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "max_retries": -1,
            },
        )
        above_maximum = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "max_retries": 6,
            },
        )
        runs = client.get("/api/runs")

    assert below_minimum.status_code == 422
    assert above_maximum.status_code == 422
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_setup_requests_skill_analysis_without_creating_run(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    dependencies = client.app.state.dependencies

    def analyze(target: TargetDescriptor) -> SkillAnalysisReport:
        return SkillAnalysisReport(
            id="run-setup-report",
            target_ref=target.ref,
            target_descriptor_sha256=target.content_sha256,
            analyzer_version="1",
            status=SkillAnalysisStatus.COMPLETED,
        )

    dependencies.skill_analysis = SkillAnalysis(dependencies.repository, analyze)

    with client:
        response = client.post(
            "/api/evaluations/skill-analysis",
            json={"version": "loan-agent-v2-fixed"},
        )
        runs = client.get("/api/runs")

    assert response.status_code == 201
    assert response.json()["id"] == "run-setup-report"
    assert response.json()["target_ref"]["external_version_id"] == (
        "loan-agent-v2-fixed"
    )
    assert dependencies.repository.get_skill_analysis_report(
        "run-setup-report"
    ) is not None
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_setup_analysis_rejects_unknown_target_without_side_effects(
    tmp_path,
) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        response = client.post(
            "/api/evaluations/skill-analysis",
            json={"version": "missing-version"},
        )
        runs = client.get("/api/runs")

    assert response.status_code == 422
    assert response.json()["detail"] == "unknown demo Target version: missing-version"
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_setup_analysis_reports_unavailable_analyzer(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    dependencies = client.app.state.dependencies
    dependencies.skill_analysis = SkillAnalysis(dependencies.repository)

    with client:
        response = client.post(
            "/api/evaluations/skill-analysis",
            json={"version": "loan-agent-v2-fixed"},
        )
        runs = client.get("/api/runs")

    assert response.status_code == 503
    assert response.json()["detail"] == "Skill analysis is unavailable"
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_route_rejects_unknown_target_without_creating_run(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    with client:
        response = client.post(
            "/api/evaluations",
            json={
                "version": "unknown-version",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
            },
        )
        runs = client.get("/api/runs")

    assert response.status_code == 422
    assert response.json()["detail"] == "unknown demo Target version: unknown-version"
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_route_rejects_empty_evaluator_selection(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    with client:
        response = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "evaluator_ids": [],
            },
        )
        runs = client.get("/api/runs")

    assert response.status_code == 422
    assert response.json()["detail"] == "at least one Evaluator is required"
    assert dispatcher.run_ids == []
    assert runs.json() == []


def test_run_route_persists_failed_run_when_dispatch_fails(tmp_path) -> None:
    dispatcher = RecordingDispatcher(ConnectionError("redis password=secret"))
    client, _ = _client(tmp_path, dispatcher)

    with client:
        response = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
            },
        )
        failed_runs = client.get("/api/runs", params={"status": "failed"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Evaluation dispatch service is unavailable"
    )
    assert len(failed_runs.json()) == 1
    assert failed_runs.json()[0]["error"] == "Run dispatch failed: ConnectionError"
    assert "secret" not in failed_runs.text


def test_run_status_returns_not_found(tmp_path) -> None:
    client, _ = _client(tmp_path)

    with client:
        response = client.get("/api/runs/missing/status")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown EvaluationRun: missing"


def test_run_route_cancels_queued_run_idempotently_and_updates_activity(
    tmp_path,
) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        launched = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
            },
        )
        run_id = launched.json()["run_id"]
        cancelled = client.post(f"/api/runs/{run_id}/cancel")
        duplicate = client.post(f"/api/runs/{run_id}/cancel")
        listed = client.get("/api/runs", params={"status": "cancelled"})
        activity = client.get("/api/runs/activity")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["completed_at"] is not None
    assert duplicate.status_code == 200
    assert duplicate.json() == cancelled.json()
    assert dispatcher.cancelled_run_ids == [run_id]
    assert [run["id"] for run in listed.json()] == [run_id]
    assert activity.json()["status_counts"]["cancelled"] == 1
    assert activity.json()["recent"][0]["run_id"] == run_id


def test_run_route_cancels_running_run(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    repository = client.app.state.dependencies.repository

    with client:
        launched = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
            },
        )
        run_id = launched.json()["run_id"]
        pending = repository.get_run(run_id)
        assert pending is not None
        running = repository.claim_pending_run(run_id, pending.created_at)
        assert running is not None
        response = client.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["started_at"] == running.model_dump(mode="json")[
        "started_at"
    ]
    assert repository.get_run(run_id).status is RunStatus.CANCELLED
    assert dispatcher.cancelled_run_ids == [run_id]


def test_run_route_rejects_unknown_and_terminal_cancellation(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    dependencies = client.app.state.dependencies
    repository = dependencies.repository
    completed = dependencies.execute_demo_run("loan-agent-v2-fixed")
    failed_pending = dependencies.runs.create_run(
        completed.manifest.target,
        dataset_id=LOAN_DATASET.id,
        dataset_version=1,
    )
    failed_running = repository.claim_pending_run(
        failed_pending.id,
        failed_pending.created_at,
    )
    assert failed_running is not None
    failed = transition_run(
        failed_running,
        RunStatus.FAILED,
        error="Target failed",
    )
    repository.save_run(failed)

    with client:
        missing = client.post("/api/runs/missing/cancel")
        completed_response = client.post(
            f"/api/runs/{completed.id}/cancel"
        )
        failed_response = client.post(f"/api/runs/{failed.id}/cancel")

    assert missing.status_code == 404
    assert missing.json()["detail"] == "unknown EvaluationRun: missing"
    assert completed_response.status_code == 409
    assert completed_response.json()["detail"] == (
        "cannot cancel completed EvaluationRun"
    )
    assert failed_response.status_code == 409
    assert failed_response.json()["detail"] == (
        "cannot cancel failed EvaluationRun"
    )
    assert dispatcher.cancelled_run_ids == []


def test_run_manifest_returns_exact_pending_execution_provenance(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)

    with client:
        launched = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "case_ids": ["high-risk-approval"],
                "evaluator_ids": ["skill-routing", "final-state"],
                "timeout_seconds": 60,
                "max_parallel_cases": 4,
            },
        )
        run_id = launched.json()["run_id"]
        response = client.get(f"/api/runs/{run_id}/manifest")

    stored = client.app.state.dependencies.repository.get_run(run_id)
    assert stored is not None
    assert launched.status_code == 202
    assert response.status_code == 200
    assert response.json() == stored.manifest.model_dump(mode="json")
    assert stored.status.value == "pending"
    assert dispatcher.run_ids == [run_id]


def test_run_manifest_returns_not_found(tmp_path) -> None:
    client, _ = _client(tmp_path)

    with client:
        response = client.get("/api/runs/missing/manifest")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown EvaluationRun: missing"

def test_run_route_accepts_reproducible_case_subset(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    datasets = client.app.state.dependencies.datasets
    dataset = datasets.create_dataset("Route Subset Dataset")
    datasets.create_draft(dataset.id)
    datasets.save_case(
        dataset.id,
        Case(
            id="first",
            name="First",
            turns=(CaseTurn(id="first-turn", input={"risk": "high"}),),
        ),
    )
    datasets.save_case(
        dataset.id,
        Case(
            id="second",
            name="Second",
            turns=(CaseTurn(id="second-turn", input={"risk": "low"}),),
        ),
    )
    datasets.publish_draft(dataset.id)
    with client:
        response = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": dataset.id,
                "dataset_version": 1,
                "case_ids": ["second"],
                "evaluator_ids": ["skill-routing"],
            },
        )
        run_id = response.json()["run_id"]
        run = client.get("/api/runs").json()[0]

    assert response.status_code == 202
    assert dispatcher.run_ids == [run_id]
    assert len(run["manifest"]["dataset"]["cases"]) == 2
    assert run["manifest"]["selected_case_ids"] == ["second"]


def test_run_route_rejects_unknown_case_subset(tmp_path) -> None:
    client, dispatcher = _client(tmp_path)
    with client:
        response = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "case_ids": ["missing-case"],
            },
        )
        runs = client.get("/api/runs")

    assert response.status_code == 422
    assert "selected_case_ids reference unknown Cases: missing-case" in (
        response.json()["detail"]
    )
    assert dispatcher.run_ids == []
    assert runs.json() == []
