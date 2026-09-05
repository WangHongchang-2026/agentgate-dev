from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agentgate.domain import (
    FindingSeverity,
    ReviewDecision,
    SkillAnalysisFinding,
    SkillAnalysisReport,
    SkillAnalysisReview,
    SkillAnalysisStatus,
    TargetRef,
    TargetType,
)


def target_ref() -> TargetRef:
    return TargetRef(
        source_id="customer-platform",
        target_type=TargetType.AGENT,
        external_target_id="loan-agent",
        external_version_id="3",
    )


def finding(**overrides: object) -> SkillAnalysisFinding:
    values: dict[str, object] = {
        "id": "finding-1",
        "check_id": "skill_relationships.semantic_overlap",
        "category": "skill_confusion",
        "severity": FindingSeverity.HIGH,
        "confidence": 0.91,
        "skill_ids": ("limit-query", "loan-query"),
        "reason": "The two descriptions claim the same request.",
        "evidence": ({"source": "skill_description", "redacted": "query limit"},),
        "suggestions": ("Clarify the ownership boundary.",),
    }
    values.update(overrides)
    return SkillAnalysisFinding(**values)


def report(**overrides: object) -> SkillAnalysisReport:
    values: dict[str, object] = {
        "id": "report-1",
        "target_ref": target_ref(),
        "target_descriptor_sha256": "a" * 64,
        "analyzer_version": "2026.09.1",
        "analyzer_config": {"checks": ["description_quality", "semantic_overlap"]},
        "status": SkillAnalysisStatus.COMPLETED,
        "findings": (finding(),),
        "risk_matrix": (
            {
                "left_skill_id": "limit-query",
                "right_skill_id": "loan-query",
                "confusion_risk": 0.91,
            },
        ),
        "created_at": datetime(2026, 9, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return SkillAnalysisReport(**values)


def test_finding_is_extensible_and_recursively_immutable() -> None:
    value = finding()

    assert value.category == "skill_confusion"
    assert value.evidence[0]["redacted"] == "query limit"
    with pytest.raises(TypeError):
        value.evidence[0]["redacted"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_confidence_outside_unit_interval(confidence: float) -> None:
    with pytest.raises(ValidationError):
        finding(confidence=confidence)


def test_finding_requires_evidence_and_unique_skill_ids() -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        finding(evidence=())
    with pytest.raises(ValidationError, match="duplicate"):
        finding(skill_ids=("loan-query", "loan-query"))


def test_report_hash_ignores_identity_and_creation_time() -> None:
    first = report()
    second = report(
        id="report-2",
        created_at=first.created_at + timedelta(hours=2),
    )

    assert first.content_sha256 == second.content_sha256


def test_report_rejects_hash_mismatch_and_duplicate_findings() -> None:
    with pytest.raises(ValidationError, match="content hash mismatch"):
        report(content_sha256="b" * 64)
    with pytest.raises(ValidationError, match="unique"):
        report(findings=(finding(), finding()))


def test_report_status_matches_errors_and_outputs() -> None:
    error = ({"analyzer_id": "llm-semantic", "message": "timeout"},)

    partial = report(status=SkillAnalysisStatus.PARTIAL, errors=error)
    assert partial.errors[0]["message"] == "timeout"

    with pytest.raises(ValidationError, match="completed.*errors"):
        report(errors=error)
    with pytest.raises(ValidationError, match="partial.*error"):
        report(status=SkillAnalysisStatus.PARTIAL, errors=())
    with pytest.raises(ValidationError, match="cannot contain analysis output"):
        report(status=SkillAnalysisStatus.FAILED, errors=error)


def test_review_is_separate_and_normalizes_timestamp_to_utc() -> None:
    review = SkillAnalysisReview(
        finding_id="finding-1",
        decision=ReviewDecision.ACCEPTED_RISK,
        reviewer_id="reviewer-7",
        comment="Known overlap during migration.",
        reviewed_at=datetime(2026, 9, 5, 8, tzinfo=timezone(timedelta(hours=8))),
    )

    assert review.reviewed_at == datetime(2026, 9, 5, tzinfo=UTC)


def test_review_rejects_blank_identity_and_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="reviewer_id must not be blank"):
        SkillAnalysisReview(
            finding_id="finding-1",
            decision=ReviewDecision.CONFIRMED,
            reviewer_id=" ",
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        SkillAnalysisReview(
            finding_id="finding-1",
            decision=ReviewDecision.CONFIRMED,
            reviewer_id="reviewer-7",
            reviewed_at=datetime(2026, 9, 5),
        )
