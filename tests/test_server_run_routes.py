from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import Case, CaseTurn
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.runs import router


class RecordingDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self.run_ids: list[str] = []
        self.error = error

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if self.error is not None:
            raise self.error


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
    assert listed.json()[0]["manifest"]["max_parallel_cases"] == 1
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
                "max_parallel_cases": 4,
            },
        )
        runs = client.get("/api/runs")

    assert launched.status_code == 202
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
    assert [case["id"] for case in run["manifest"]["dataset"]["cases"]] == [
        "second"
    ]
    assert "Run case subset" in run["manifest"]["dataset"]["notes"]


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
    assert response.json()["detail"] == "case_ids reference unknown Cases: missing-case"
    assert dispatcher.run_ids == []
    assert runs.json() == []
