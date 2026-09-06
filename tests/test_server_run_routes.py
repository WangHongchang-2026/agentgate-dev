from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.demo.loan import LOAN_DATASET
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.runs import router


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    app.state.dependencies = build_dependencies(tmp_path / "run-routes.db")
    app.include_router(router)
    return TestClient(app)


def test_run_routes_submit_and_list_completed_demo_evaluation(tmp_path) -> None:
    with _client(tmp_path) as client:
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
        listed = client.get("/api/runs")

    assert launched.status_code == 201
    assert launched.json()["status"] == "completed"
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [launched.json()["id"]]


def test_run_route_rejects_unknown_target_without_creating_run(tmp_path) -> None:
    with _client(tmp_path) as client:
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
    assert runs.json() == []


def test_run_route_rejects_empty_evaluator_selection(tmp_path) -> None:
    with _client(tmp_path) as client:
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
    assert runs.json() == []
