from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import TargetSnapshot
from agentgate.server.dependencies import ServerDependencies, build_dependencies
from agentgate.server.routes.results import router


def _client(dependencies: ServerDependencies) -> TestClient:
    app = FastAPI()
    app.state.dependencies = dependencies
    app.include_router(router)
    return TestClient(app)


def _target() -> TargetSnapshot:
    return build_demo_target_snapshot(
        get_demo_target_descriptor("loan-agent-v2-fixed")
    )


def test_result_routes_return_overview_report_and_trace(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "result-routes.db")
    run = dependencies.execute_demo_run(
        "loan-agent-v2-fixed",
        dataset_version=1,
    )

    with _client(dependencies) as client:
        overview = client.get("/api/overview")
        report = client.get(f"/api/runs/{run.id}")
        trace = client.get(
            f"/api/runs/{run.id}/traces/high-risk-approval"
        )

    assert overview.status_code == 200
    assert overview.json()["total_runs"] == 1
    assert overview.json()["completed_runs"] == 1
    assert overview.json()["latest"]["run"]["id"] == run.id
    assert report.status_code == 200
    assert report.json()["release_gate"]["outcome"] == "pass"
    assert trace.status_code == 200
    assert trace.json()["run_id"] == run.id
    assert trace.json()["case_id"] == "high-risk-approval"


def test_result_routes_return_not_found_for_unknown_resources(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "missing-result-routes.db")

    with _client(dependencies) as client:
        report = client.get("/api/runs/missing")
        trace = client.get("/api/runs/missing/traces/missing")

    assert report.status_code == 404
    assert report.json()["detail"] == "unknown EvaluationRun: missing"
    assert trace.status_code == 404
    assert trace.json()["detail"] == "unknown EvaluationRun: missing"


def test_result_route_rejects_report_for_pending_run(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "pending-result-routes.db")
    run = dependencies.runs.create_run(_target(), dataset_id=LOAN_DATASET.id)

    with _client(dependencies) as client:
        response = client.get(f"/api/runs/{run.id}")

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "EvaluationReport requires a completed EvaluationRun"
    )
