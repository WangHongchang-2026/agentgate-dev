from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import CaseDifficulty, TargetSnapshot
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


def test_result_route_returns_available_analytics_breakdowns(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "result-analytics-route.db")
    run = dependencies.execute_demo_run("loan-agent-v1-risky")

    with _client(dependencies) as client:
        response = client.get(f"/api/runs/{run.id}/analytics")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run.id
    assert body["by_evaluator"]["available"] is True
    assert body["by_category"]["buckets"][0]["key"] == "boundary"
    assert body["by_difficulty"]["buckets"][0]["key"] == "hard"
    assert {bucket["key"] for bucket in body["by_tag"]["buckets"]} == {
        "high-risk",
        "policy",
    }
    assert body["by_routing"]["buckets"][0]["key"] == "loan_approval"
    assert body["by_tool_use"]["available"] is True
    assert body["by_failure_type"]["available"] is True


def test_result_analytics_route_translates_run_errors(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "result-analytics-errors.db")
    pending = dependencies.runs.create_run(
        _target(),
        dataset_id=LOAN_DATASET.id,
    )

    with _client(dependencies) as client:
        missing = client.get("/api/runs/missing/analytics")
        incomplete = client.get(f"/api/runs/{pending.id}/analytics")

    assert missing.status_code == 404
    assert missing.json()["detail"] == "unknown EvaluationRun: missing"
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"] == (
        "Result analytics requires a completed EvaluationRun"
    )


def test_result_routes_return_historical_case_and_write_back_failure(
    tmp_path,
) -> None:
    dependencies = build_dependencies(tmp_path / "result-writeback-routes.db")
    run = dependencies.execute_demo_run(
        "loan-agent-v1-risky",
        dataset_version=1,
    )
    source_case = run.manifest.execution_cases[0]
    edited_case = source_case.model_copy(
        update={
            "difficulty": CaseDifficulty.EASY,
            "notes": "Clarified after reviewing this failed Result.",
        }
    )

    with _client(dependencies) as client:
        detail = client.get(
            f"/api/runs/{run.id}/cases/{source_case.id}"
        )
        writeback = client.post(
            f"/api/runs/{run.id}/cases/{source_case.id}/writeback",
            json={"case": edited_case.model_dump(mode="json")},
        )

    assert detail.status_code == 200
    assert detail.json()["dataset_version"] == 1
    assert detail.json()["case"]["difficulty"] == "hard"
    assert detail.json()["case"]["notes"] == source_case.notes
    assert any(
        result["outcome"] == "fail" for result in detail.json()["results"]
    )
    assert writeback.status_code == 200
    body = writeback.json()
    assert body["source_run_id"] == run.id
    assert body["source_dataset_version"] == 1
    assert body["draft"]["status"] == "draft"
    assert body["draft"]["cases"][0]["difficulty"] == "easy"
    assert body["draft"]["cases"][0]["notes"] == edited_case.notes
    historical = dependencies.datasets.get_version(
        run.manifest.dataset.dataset_id,
        1,
    )
    assert historical.cases[0] == source_case


def test_result_case_routes_translate_writeback_failures(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "result-writeback-errors.db")
    risky = dependencies.execute_demo_run("loan-agent-v1-risky")
    fixed = dependencies.execute_demo_run("loan-agent-v2-fixed")
    risky_case = risky.manifest.execution_cases[0]
    fixed_case = fixed.manifest.execution_cases[0]

    with _client(dependencies) as client:
        missing_run = client.get("/api/runs/missing/cases/case")
        missing_case = client.get(f"/api/runs/{risky.id}/cases/missing")
        nonfailed = client.post(
            f"/api/runs/{fixed.id}/cases/{fixed_case.id}/writeback",
            json={"case": fixed_case.model_dump(mode="json")},
        )
        changed_payload = risky_case.model_copy(update={"id": "changed"})
        changed_identity = client.post(
            f"/api/runs/{risky.id}/cases/{risky_case.id}/writeback",
            json={"case": changed_payload.model_dump(mode="json")},
        )

    assert missing_run.status_code == 404
    assert missing_case.status_code == 404
    assert nonfailed.status_code == 409
    assert nonfailed.json()["detail"] == (
        f"Case has no failed Result: {fixed.id}/{fixed_case.id}"
    )
    assert changed_identity.status_code == 422
    assert changed_identity.json()["detail"] == (
        "edited Case id must match the historical Case id"
    )
