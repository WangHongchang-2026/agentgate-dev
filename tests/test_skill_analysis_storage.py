from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from agentgate.domain import (
    FindingSeverity,
    ReviewDecision,
    SkillAnalysisFinding,
    SkillAnalysisReport,
    SkillAnalysisReview,
    SkillAnalysisStatus,
    TargetDescriptor,
    TargetRef,
    TargetType,
)
from agentgate.storage.sqlite import SQLiteRepository


CREATED_AT = datetime(2026, 9, 8, tzinfo=UTC)


def descriptor() -> TargetDescriptor:
    return TargetDescriptor(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="1",
        ),
        display_name="Loan Agent",
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


def report(
    target: TargetDescriptor,
    *,
    report_id: str = "report-1",
    created_at: datetime = CREATED_AT,
) -> SkillAnalysisReport:
    return SkillAnalysisReport(
        id=report_id,
        target_ref=target.ref,
        target_descriptor_sha256=target.content_sha256,
        analyzer_version="1",
        status=SkillAnalysisStatus.COMPLETED,
        findings=(finding(),),
        created_at=created_at,
    )


def review(
    decision: ReviewDecision = ReviewDecision.CONFIRMED,
) -> SkillAnalysisReview:
    return SkillAnalysisReview(
        finding_id="finding-1",
        decision=decision,
        reviewer_id="reviewer-1",
        reviewed_at=CREATED_AT,
    )


def repository_with_target(tmp_path) -> tuple[SQLiteRepository, TargetDescriptor]:
    repository = SQLiteRepository(tmp_path / "skill-analysis.db")
    target = descriptor()
    repository.save_target_descriptor(target)
    return repository, target


def test_report_round_trip_and_newest_first_listing(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    older = report(target)
    newer = report(
        target,
        report_id="report-2",
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    repository.save_skill_analysis_report(older)
    repository.save_skill_analysis_report(newer)

    assert repository.get_skill_analysis_report(older.id) == older
    assert repository.list_skill_analysis_reports(target.content_sha256) == [
        newer,
        older,
    ]


def test_saving_same_report_is_idempotent(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    value = report(target)

    repository.save_skill_analysis_report(value)
    repository.save_skill_analysis_report(value)

    assert repository.list_skill_analysis_reports(target.content_sha256) == [value]


def test_report_id_cannot_be_reused_for_different_content(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    original = report(target)
    changed = SkillAnalysisReport.model_validate(
        {
            **original.model_dump(mode="json"),
            "analyzer_version": "2",
            "content_sha256": "",
        }
    )
    repository.save_skill_analysis_report(original)

    with pytest.raises(ValueError, match="immutable"):
        repository.save_skill_analysis_report(changed)


def test_report_requires_a_persisted_target_descriptor(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "missing-target.db")

    with pytest.raises(sqlite3.IntegrityError):
        repository.save_skill_analysis_report(report(descriptor()))


def test_report_list_requires_positive_limit(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)

    with pytest.raises(ValueError, match="limit"):
        repository.list_skill_analysis_reports(target.content_sha256, limit=0)


def test_review_round_trip(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    value = report(target)
    repository.save_skill_analysis_report(value)
    current = review()

    repository.save_skill_analysis_review(value.id, current)

    assert repository.list_skill_analysis_reviews(value.id) == [current]


def test_saving_review_replaces_current_finding_review(tmp_path) -> None:
    repository, target = repository_with_target(tmp_path)
    value = report(target)
    repository.save_skill_analysis_report(value)
    repository.save_skill_analysis_review(value.id, review())
    replacement = review(ReviewDecision.DISMISSED)

    repository.save_skill_analysis_review(value.id, replacement)

    assert repository.list_skill_analysis_reviews(value.id) == [replacement]


def test_review_requires_an_existing_report(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "missing-report.db")

    with pytest.raises(sqlite3.IntegrityError):
        repository.save_skill_analysis_review("missing-report", review())
