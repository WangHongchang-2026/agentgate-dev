import pytest
from fastapi.testclient import TestClient

from agentgate.application import SkillAnalysis
from agentgate.application.evaluator_management import EvaluatorManagement
from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import FrozenJsonObject
from agentgate.evaluator.judge import JudgeRequest, JudgeResponse
from agentgate.integrations.model_providers.environment import ConfiguredJudgeModel
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.server.app import create_app
from agentgate.server.dependencies import ServerDependencies, build_dependencies


class RecordingDispatcher:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)


class RecordingJudgeClient:
    provider_id = "company-llm"

    def __init__(self) -> None:
        self.close_count = 0

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        del request
        raise AssertionError("dependency construction must not call the model")

    def close(self) -> None:
        self.close_count += 1

    def __repr__(self) -> str:
        return "RecordingJudgeClient(api_key='raw-secret')"


def judge_configuration(client: RecordingJudgeClient) -> ConfiguredJudgeModel:
    return ConfiguredJudgeModel(
        provider_id=client.provider_id,
        model_id="judge-model",
        credential_ref="env:AGENTGATE_JUDGE_API_KEY",
        client=client,  # type: ignore[arg-type]
    )


def test_application_factory_registers_dependencies_and_routes(tmp_path) -> None:
    application = create_app(tmp_path / "server-app.db")

    assert isinstance(application.state.dependencies, ServerDependencies)
    assert isinstance(
        application.state.dependencies.evaluators,
        EvaluatorManagement,
    )
    assert (
        application.state.dependencies.runs.evaluator_management
        is application.state.dependencies.evaluators
    )
    assert isinstance(
        application.state.dependencies.skill_analysis,
        SkillAnalysis,
    )
    assert not hasattr(application.state, "repository")
    assert not hasattr(application.state, "service")

    paths = application.openapi()["paths"]
    assert {
        "/health",
        "/api/overview",
        "/api/versions",
        "/api/evaluators",
        "/api/evaluators/{evaluator_id}",
        "/api/evaluators/{evaluator_id}/versions",
        "/api/evaluators/{evaluator_id}/versions/{version}",
        "/api/evaluators/{evaluator_id}/drafts/current",
        "/api/evaluators/{evaluator_id}/drafts",
        "/api/evaluators/{evaluator_id}/drafts/publish",
        "/api/datasets",
        "/api/runs",
        "/api/runs/activity",
        "/api/evaluations",
        "/api/runs/{run_id}/status",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/traces/{case_id}",
        "/api/skill-analysis/reports",
        "/api/skill-analysis/reports/{report_id}",
        (
            "/api/skill-analysis/reports/{report_id}/findings/"
            "{finding_id}/review"
        ),
        "/v1/traces",
    }.issubset(paths)
    assert set(paths["/api/evaluators"]) == {"get", "post"}

    with TestClient(application) as client:
        evaluator_response = client.get("/api/evaluators")

    assert evaluator_response.status_code == 200
    assert len(evaluator_response.json()) == 7
    assert {item["source"] for item in evaluator_response.json()} == {"builtin"}


def test_dependencies_compose_configured_judge_and_close_it_once(
    tmp_path, monkeypatch
) -> None:
    client = RecordingJudgeClient()
    monkeypatch.setattr(
        "agentgate.server.dependencies.load_judge_model_from_environment",
        lambda: judge_configuration(client),
    )

    dependencies = build_dependencies(
        tmp_path / "server-judge.db",
        RecordingDispatcher(),
    )

    assert dependencies.evaluators.default_specs[-1].id == "answer-quality"
    assert dependencies.runs.evaluator_management is dependencies.evaluators
    assert "raw-secret" not in repr(dependencies)
    dependencies.close()
    dependencies.close()
    assert client.close_count == 1


def test_dependencies_close_judge_when_composition_fails(
    tmp_path, monkeypatch
) -> None:
    client = RecordingJudgeClient()
    monkeypatch.setattr(
        "agentgate.server.dependencies.load_judge_model_from_environment",
        lambda: judge_configuration(client),
    )

    def fail_composition(*args, **kwargs) -> None:
        del args
        del kwargs
        raise ValueError("composition failed")

    monkeypatch.setattr(
        "agentgate.server.dependencies.build_default_evaluator_management",
        fail_composition,
    )

    with pytest.raises(ValueError, match="composition failed"):
        build_dependencies(
            tmp_path / "server-judge-failure.db",
            RecordingDispatcher(),
        )

    assert client.close_count == 1


def test_application_lifespan_closes_configured_judge(
    tmp_path, monkeypatch
) -> None:
    judge_client = RecordingJudgeClient()
    monkeypatch.setattr(
        "agentgate.server.dependencies.load_judge_model_from_environment",
        lambda: judge_configuration(judge_client),
    )
    application = create_app(
        tmp_path / "server-judge-lifespan.db",
        RecordingDispatcher(),
    )

    assert judge_client.close_count == 0
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert judge_client.close_count == 0

    assert judge_client.close_count == 1


def test_application_lifespan_closes_judge_when_startup_fails(
    tmp_path, monkeypatch
) -> None:
    judge_client = RecordingJudgeClient()
    monkeypatch.setattr(
        "agentgate.server.dependencies.load_judge_model_from_environment",
        lambda: judge_configuration(judge_client),
    )
    application = create_app(
        tmp_path / "server-judge-startup-failure.db",
        RecordingDispatcher(),
    )

    def fail_recovery() -> None:
        raise RuntimeError("recovery failed")

    monkeypatch.setattr(
        application.state.dependencies.runs,
        "fail_stale_runs",
        fail_recovery,
    )

    with pytest.raises(RuntimeError, match="recovery failed"):
        with TestClient(application):
            pass

    assert judge_client.close_count == 1


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

        stored_trace = application.state.dependencies.repository.get_trace(
            run_id, "high-risk-approval"
        )
        assert stored_trace is not None
        application.state.dependencies.repository.save_trace(
            stored_trace.model_copy(
                update={
                    "final_state": FrozenJsonObject(
                        {"status": "human_review", "api_key": "raw-secret"}
                    )
                }
            )
        )
        completed = client.get(f"/api/runs/{run_id}/status")
        report = client.get(f"/api/runs/{run_id}")
        trace = client.get(f"/api/runs/{run_id}/traces/high-risk-approval")

    assert launched.status_code == 202
    assert launched.json()["status"] == "pending"
    assert dispatcher.run_ids == [run_id]
    assert queued.json()["status"] == "pending"
    assert completed.json()["status"] == "completed"
    assert completed.json()["progress"] == 1
    assert report.status_code == 200
    assert report.json()["release_gate"]["outcome"] == "pass"
    assert trace.status_code == 200
    assert trace.json()["final_state"]["api_key"] == "[redacted]"
    assert "raw-secret" not in trace.text


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
