from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application import (
    OptimizationRunNotCompleted,
    OptimizationRunNotFound,
    OptimizationSkillAnalysisMismatch,
    OptimizationSkillAnalysisNotUsable,
    OptimizationSkillAnalysisReportNotFound,
)
from agentgate.domain import (
    OptimizationReport,
    RoutingConfusionMatrix,
    TargetRef,
    TargetType,
)
from agentgate.server.dependencies import get_dependencies
from agentgate.server.routes.optimizer import router


def report() -> OptimizationReport:
    return OptimizationReport(
        run_id="run-1",
        target_ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="v1",
        ),
        target_content_sha256="a" * 64,
        dataset_id="dataset-1",
        dataset_version=1,
        dataset_content_sha256="b" * 64,
        analyzer_version="1",
        failed_result_count=0,
        confusion_matrix=RoutingConfusionMatrix(eligible_count=0),
    )


class OptimizationStub:
    def __init__(
        self,
        value: OptimizationReport | Exception,
    ) -> None:
        self.value = value
        self.calls: list[tuple[str, str | None]] = []

    def analyze_run(
        self,
        run_id: str,
        skill_analysis_report_id: str | None = None,
    ) -> OptimizationReport:
        self.calls.append((run_id, skill_analysis_report_id))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def client_for(stub: OptimizationStub) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_dependencies] = lambda: SimpleNamespace(
        optimization=stub
    )
    return TestClient(app)


def test_returns_optimization_report_and_forwards_optional_static_report() -> None:
    stub = OptimizationStub(report())
    client = client_for(stub)

    plain = client.get("/api/runs/run-1/optimization")
    correlated = client.get(
        "/api/runs/run-1/optimization",
        params={"skill_analysis_report_id": "skill-report-1"},
    )

    assert plain.status_code == 200
    assert plain.json()["run_id"] == "run-1"
    assert correlated.status_code == 200
    assert stub.calls == [
        ("run-1", None),
        ("run-1", "skill-report-1"),
    ]


@pytest.mark.parametrize(
    ("error", "status_code"),
    (
        (OptimizationRunNotFound("missing Run"), 404),
        (
            OptimizationSkillAnalysisReportNotFound("missing static report"),
            404,
        ),
        (OptimizationRunNotCompleted("Run incomplete"), 409),
        (OptimizationSkillAnalysisMismatch("wrong Target"), 422),
        (OptimizationSkillAnalysisNotUsable("failed report"), 422),
        (ValueError("invalid input"), 422),
    ),
)
def test_maps_application_errors(
    error: Exception,
    status_code: int,
) -> None:
    response = client_for(OptimizationStub(error)).get(
        "/api/runs/run-1/optimization"
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


def test_rejects_blank_static_report_query() -> None:
    stub = OptimizationStub(report())

    response = client_for(stub).get(
        "/api/runs/run-1/optimization",
        params={"skill_analysis_report_id": ""},
    )

    assert response.status_code == 422
    assert stub.calls == []


def test_openapi_uses_optimization_report_response_schema() -> None:
    client = client_for(OptimizationStub(report()))

    response_schema = client.get("/openapi.json").json()["paths"][
        "/api/runs/{run_id}/optimization"
    ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    assert response_schema == {
        "$ref": "#/components/schemas/OptimizationReport"
    }
