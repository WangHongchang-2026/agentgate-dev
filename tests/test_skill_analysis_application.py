from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agentgate.application.skill_analysis import (
    SkillAnalysis,
    SkillAnalysisFindingNotFound,
    SkillAnalysisReportNotFound,
    SkillAnalysisTargetNotFound,
    SkillAnalysisUnavailable,
)
from agentgate.domain import (
    FindingSeverity,
    ReviewDecision,
    SkillAnalysisFinding,
    SkillAnalysisReport,
    SkillAnalysisStatus,
    TargetDescriptor,
    TargetRef,
    TargetType,
)
from agentgate.storage.sqlite import SQLiteRepository


CREATED_AT = datetime(2026, 9, 8, tzinfo=UTC)


def target_ref(target_id: str = "loan-agent") -> TargetRef:
    return TargetRef(
        source_id="demo",
        target_type=TargetType.AGENT,
        external_target_id=target_id,
        external_version_id="1",
    )


def descriptor(target_id: str = "loan-agent") -> TargetDescriptor:
    return TargetDescriptor(
        ref=target_ref(target_id),
        display_name="Loan Agent",
        fetched_at=CREATED_AT,
    )


def finding() -> SkillAnalysisFinding:
    return SkillAnalysisFinding(
        id="finding-1",
        check_id="skill_relationships.llm_pairwise",
        category="skill_confusion",
        severity=FindingSeverity.HIGH,
        confidence=0.9,
        skill_ids=("loan", "finance"),
        reason="Both Skills accept the same request.",
        evidence=({"relationship": "ambiguous"},),
    )


def report_for(
    target: TargetDescriptor,
    *,
    report_id: str = "report-1",
    created_at: datetime = CREATED_AT,
    target_ref_override: TargetRef | None = None,
    descriptor_hash: str | None = None,
) -> SkillAnalysisReport:
    return SkillAnalysisReport(
        id=report_id,
        target_ref=target_ref_override or target.ref,
        target_descriptor_sha256=descriptor_hash or target.content_sha256,
        analyzer_version="1",
        status=SkillAnalysisStatus.COMPLETED,
        findings=(finding(),),
        created_at=created_at,
    )


def repository_with_target(tmp_path) -> tuple[SQLiteRepository, TargetDescriptor]:
    repository = SQLiteRepository(tmp_path / "skill-analysis-application.db")
    target = descriptor()
    repository.save_target_descriptor(target)
    return repository, target


def test_analyze_target_resolves_descriptor_and_persists_report(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    received: list[TargetDescriptor] = []

    def analyze(value: TargetDescriptor) -> SkillAnalysisReport:
        received.append(value)
        return report_for(value)

    application = SkillAnalysis(repository, analyze)

    result = application.analyze_target(target.content_sha256)

    assert received == [target]
    assert result == report_for(target)
    assert repository.get_skill_analysis_report(result.id) == result


def test_analyze_target_rejects_unknown_descriptor(tmp_path) -> None:
    def unexpected_analyzer(_: TargetDescriptor) -> SkillAnalysisReport:
        raise AssertionError("analyzer must not run for an unknown Target")

    application = SkillAnalysis(
        SQLiteRepository(tmp_path / "unknown.db"), unexpected_analyzer
    )

    with pytest.raises(SkillAnalysisTargetNotFound):
        application.analyze_target("a" * 64)


def test_analyze_target_requires_configured_analyzer(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)

    with pytest.raises(SkillAnalysisUnavailable):
        SkillAnalysis(repository).analyze_target(target.content_sha256)


def test_analyze_target_rejects_wrong_target_reference(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    application = SkillAnalysis(
        repository,
        lambda value: report_for(
            value,
            target_ref_override=target_ref("another-agent"),
        ),
    )

    with pytest.raises(ValueError, match="another Target"):
        application.analyze_target(target.content_sha256)


def test_analyze_target_rejects_wrong_descriptor_hash(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    application = SkillAnalysis(
        repository,
        lambda value: report_for(value, descriptor_hash="b" * 64),
    )

    with pytest.raises(ValueError, match="another Target descriptor"):
        application.analyze_target(target.content_sha256)


def test_list_reports_uses_exact_descriptor(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    older = report_for(target)
    newer = report_for(
        target,
        report_id="report-2",
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    repository.save_skill_analysis_report(older)
    repository.save_skill_analysis_report(newer)

    assert SkillAnalysis(repository).list_reports(target.content_sha256) == (
        newer,
        older,
    )


def test_get_report_rejects_unknown_report(tmp_path) -> None:
    application = SkillAnalysis(SQLiteRepository(tmp_path / "missing-report.db"))

    with pytest.raises(SkillAnalysisReportNotFound):
        application.get_report("missing")


def test_record_and_list_review(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    value = report_for(target)
    repository.save_skill_analysis_report(value)
    application = SkillAnalysis(repository)

    recorded = application.record_review(
        value.id,
        "finding-1",
        ReviewDecision.CONFIRMED,
        "reviewer-1",
        "Descriptions should be separated.",
    )

    assert recorded.finding_id == "finding-1"
    assert recorded.decision is ReviewDecision.CONFIRMED
    assert application.list_reviews(value.id) == (recorded,)


def test_record_review_rejects_unknown_finding(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    value = report_for(target)
    repository.save_skill_analysis_report(value)

    with pytest.raises(SkillAnalysisFindingNotFound):
        SkillAnalysis(repository).record_review(
            value.id,
            "missing-finding",
            ReviewDecision.DISMISSED,
            "reviewer-1",
        )
