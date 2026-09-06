from fastapi.testclient import TestClient

from agentgate.demo.loan import LOAN_DATASET
from agentgate.server.app import create_app
from agentgate.server.dependencies import ServerDependencies


def test_application_factory_registers_dependencies_and_routes(tmp_path) -> None:
    application = create_app(tmp_path / "server-app.db")

    assert isinstance(application.state.dependencies, ServerDependencies)
    assert not hasattr(application.state, "repository")
    assert not hasattr(application.state, "service")

    paths = application.openapi()["paths"]
    assert {
        "/health",
        "/api/overview",
        "/api/versions",
        "/api/evaluators",
        "/api/datasets",
        "/api/runs",
        "/api/evaluations",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/traces/{case_id}",
        "/v1/traces",
    }.issubset(paths)


def test_application_factory_supports_complete_demo_workflow(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "server-workflow.db")) as client:
        launched = client.post(
            "/api/evaluations",
            json={
                "version": "loan-agent-v2-fixed",
                "dataset_id": LOAN_DATASET.id,
                "dataset_version": 1,
                "evaluator_ids": ["skill-routing", "final-state"],
            },
        )
        report = client.get(f"/api/runs/{launched.json()['id']}")

    assert launched.status_code == 201
    assert launched.json()["status"] == "completed"
    assert report.status_code == 200
    assert report.json()["release_gate"]["outcome"] == "pass"


def test_application_factory_allows_local_vite_origin(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "server-cors.db")) as client:
        response = client.options(
            "/api/datasets",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
