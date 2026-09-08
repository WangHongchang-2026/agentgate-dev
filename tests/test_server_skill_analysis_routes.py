from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application import SkillAnalysis
from agentgate.domain import (
    FindingSeverity,
    SkillAnalysisFinding,
    SkillAnalysisReport,
    SkillAnalysisStatus,
    SkillDescriptor,
    TargetDescriptor,
    TargetRef,
    TargetType,
)
from agentgate.integrations.model_providers.environment import (
    API_KEY_ENV,
    BASE_URL_ENV,
    MODEL_ID_ENV,
    PROVIDER_ID_ENV,
)
from agentgate.server.app import create_app


def descriptor() -> TargetDescriptor:
    return TargetDescriptor(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="1",
        ),
        display_name="Loan Agent",
        skills=(
            SkillDescriptor(
                external_skill_id="loan",
                external_version_id="1",
                name="Loan",
                description="Handle loan applications.",
            ),
            SkillDescriptor(
                external_skill_id="finance",
                external_version_id="1",
                name="Finance",
                description="Handle financing requests.",
            ),
        ),
    )


def report_for(target: TargetDescriptor) -> SkillAnalysisReport:
    return SkillAnalysisReport(
        id="report-1",
        target_ref=target.ref,
        target_descriptor_sha256=target.content_sha256,
        analyzer_version="1",
        status=SkillAnalysisStatus.COMPLETED,
        findings=(
            SkillAnalysisFinding(
                id="finding-1",
                check_id="skill_relationships.llm_pairwise",
                category="skill_confusion",
                severity=FindingSeverity.HIGH,
                confidence=0.9,
                skill_ids=("finance", "loan"),
                reason="Both Skills accept the same request.",
                evidence=({"relationship": "ambiguous"},),
            ),
        ),
    )


def build_test_app(
    tmp_path,
    monkeypatch,
    analyzer: Callable[[TargetDescriptor], SkillAnalysisReport] | None,
) -> tuple[FastAPI, TargetDescriptor]:
    for name in (PROVIDER_ID_ENV, BASE_URL_ENV, API_KEY_ENV, MODEL_ID_ENV):
        monkeypatch.delenv(name, raising=False)
    application = create_app(tmp_path / "skill-analysis-api.db")
    target = descriptor()
    dependencies = application.state.dependencies
    dependencies.targets.register_descriptor(target)
    dependencies.skill_analysis = SkillAnalysis(
        dependencies.repository,
        analyzer,
    )
    return application, target


def deterministic_analyzer(target: TargetDescriptor) -> SkillAnalysisReport:
    return report_for(target)


def test_analyze_list_and_get_report(tmp_path, monkeypatch) -> None:
    application, target = build_test_app(
        tmp_path, monkeypatch, deterministic_analyzer
    )

    with TestClient(application) as client:
        created = client.post(
            "/api/skill-analysis/reports",
            json={"target_descriptor_sha256": target.content_sha256},
        )
        listed = client.get(
            "/api/skill-analysis/reports",
            params={"target_descriptor_sha256": target.content_sha256},
        )
        detail = client.get("/api/skill-analysis/reports/report-1")

    assert created.status_code == 201
    assert created.json()["id"] == "report-1"
    assert [item["id"] for item in listed.json()] == ["report-1"]
    assert detail.json()["report"]["id"] == "report-1"
    assert detail.json()["reviews"] == []


def test_review_is_created_and_replaced(tmp_path, monkeypatch) -> None:
    application, target = build_test_app(
        tmp_path, monkeypatch, deterministic_analyzer
    )

    with TestClient(application) as client:
        client.post(
            "/api/skill-analysis/reports",
            json={"target_descriptor_sha256": target.content_sha256},
        )
        first = client.put(
            "/api/skill-analysis/reports/report-1/findings/finding-1/review",
            json={
                "decision": "confirmed",
                "reviewer_id": "reviewer-1",
                "comment": "The routing is ambiguous.",
            },
        )
        replacement = client.put(
            "/api/skill-analysis/reports/report-1/findings/finding-1/review",
            json={
                "decision": "dismissed",
                "reviewer_id": "reviewer-2",
            },
        )
        detail = client.get("/api/skill-analysis/reports/report-1")

    assert first.status_code == 200
    assert replacement.status_code == 200
    assert detail.json()["reviews"] == [replacement.json()]


def test_unknown_target_returns_not_found(tmp_path, monkeypatch) -> None:
    application, _ = build_test_app(
        tmp_path, monkeypatch, deterministic_analyzer
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/skill-analysis/reports",
            json={"target_descriptor_sha256": "a" * 64},
        )

    assert response.status_code == 404


def test_unknown_report_returns_not_found(tmp_path, monkeypatch) -> None:
    application, _ = build_test_app(
        tmp_path, monkeypatch, deterministic_analyzer
    )

    with TestClient(application) as client:
        response = client.get("/api/skill-analysis/reports/missing")

    assert response.status_code == 404


def test_unknown_finding_returns_not_found(tmp_path, monkeypatch) -> None:
    application, target = build_test_app(
        tmp_path, monkeypatch, deterministic_analyzer
    )

    with TestClient(application) as client:
        client.post(
            "/api/skill-analysis/reports",
            json={"target_descriptor_sha256": target.content_sha256},
        )
        response = client.put(
            "/api/skill-analysis/reports/report-1/findings/missing/review",
            json={"decision": "dismissed", "reviewer_id": "reviewer-1"},
        )

    assert response.status_code == 404


def test_unconfigured_analyzer_returns_service_unavailable(
    tmp_path, monkeypatch
) -> None:
    application, target = build_test_app(tmp_path, monkeypatch, None)

    with TestClient(application) as client:
        response = client.post(
            "/api/skill-analysis/reports",
            json={"target_descriptor_sha256": target.content_sha256},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Skill analysis is unavailable"


def test_invalid_hash_and_list_limit_return_unprocessable(
    tmp_path, monkeypatch
) -> None:
    application, target = build_test_app(
        tmp_path, monkeypatch, deterministic_analyzer
    )

    with TestClient(application) as client:
        invalid_hash = client.post(
            "/api/skill-analysis/reports",
            json={"target_descriptor_sha256": "invalid"},
        )
        invalid_limit = client.get(
            "/api/skill-analysis/reports",
            params={
                "target_descriptor_sha256": target.content_sha256,
                "limit": 0,
            },
        )

    assert invalid_hash.status_code == 422
    assert invalid_limit.status_code == 422


def test_request_contracts_reject_unknown_fields_and_decisions(
    tmp_path, monkeypatch
) -> None:
    application, target = build_test_app(
        tmp_path, monkeypatch, deterministic_analyzer
    )

    with TestClient(application) as client:
        extra_field = client.post(
            "/api/skill-analysis/reports",
            json={
                "target_descriptor_sha256": target.content_sha256,
                "unexpected": True,
            },
        )
        invalid_decision = client.put(
            "/api/skill-analysis/reports/missing/findings/missing/review",
            json={"decision": "unknown", "reviewer_id": "reviewer-1"},
        )

    assert extra_field.status_code == 422
    assert invalid_decision.status_code == 422
