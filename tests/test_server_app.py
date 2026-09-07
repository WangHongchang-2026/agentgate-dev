from fastapi.testclient import TestClient

from agentgate.demo.loan import LOAN_DATASET
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.server.app import create_app
from agentgate.server.dependencies import ServerDependencies


class RecordingDispatcher:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)


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
        "/api/runs/activity",
        "/api/evaluations",
        "/api/runs/{run_id}/status",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/traces/{case_id}",
        "/v1/traces",
    }.issubset(paths)


def test_application_factory_supports_async_demo_workflow(tmp_path) -> None:
    dispatcher = RecordingDispatcher()
    application = create_app(tmp_path / "server-workflow.db", dispatcher)
    with TestClient(application) as client:
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
        queued = client.get(f"/api/runs/{run_id}/status")

        capture = InMemoryTraceCapture()
        try:
            application.state.dependencies.runs.execute_run(
                run_id,
                DemoLoanTargetAdapter(capture),
                capture.resolve,
            )
        finally:
            capture.shutdown()

        completed = client.get(f"/api/runs/{run_id}/status")
        report = client.get(f"/api/runs/{run_id}")

    assert launched.status_code == 202
    assert launched.json()["status"] == "pending"
    assert dispatcher.run_ids == [run_id]
    assert queued.json()["status"] == "pending"
    assert completed.json()["status"] == "completed"
    assert completed.json()["progress"] == 1
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
