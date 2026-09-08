"""Application workflows for static Skill analysis and human review."""

from __future__ import annotations

from collections.abc import Callable

from agentgate.domain import (
    ReviewDecision,
    SkillAnalysisReport,
    SkillAnalysisReview,
    TargetDescriptor,
)
from agentgate.domain.base import require_non_blank, require_sha256
from agentgate.storage.repository import AgentGateRepository


SkillAnalyzer = Callable[[TargetDescriptor], SkillAnalysisReport]


class SkillAnalysisUnavailable(RuntimeError):
    """No Skill analyzer is configured for this process."""


class SkillAnalysisTargetNotFound(LookupError):
    """An exact Target descriptor does not exist."""


class SkillAnalysisReportNotFound(LookupError):
    """A Skill-analysis report does not exist."""


class SkillAnalysisFindingNotFound(LookupError):
    """A finding does not exist in the selected report."""


class SkillAnalysis:
    """Coordinate static analysis and review of exact Target descriptors."""

    __slots__ = ("repository", "_analyzer")

    def __init__(
        self,
        repository: AgentGateRepository,
        analyzer: SkillAnalyzer | None = None,
    ) -> None:
        self.repository = repository
        self._analyzer = analyzer

    def analyze_target(
        self, target_descriptor_sha256: str
    ) -> SkillAnalysisReport:
        descriptor = self._target(target_descriptor_sha256)
        if self._analyzer is None:
            raise SkillAnalysisUnavailable("Skill analyzer is not configured")
        report = self._analyzer(descriptor)
        if report.target_ref != descriptor.ref:
            raise ValueError("Skill analyzer returned a report for another Target")
        if report.target_descriptor_sha256 != descriptor.content_sha256:
            raise ValueError(
                "Skill analyzer returned a report for another Target descriptor"
            )
        self.repository.save_skill_analysis_report(report)
        return report

    def get_report(self, report_id: str) -> SkillAnalysisReport:
        identifier = require_non_blank(report_id, "SkillAnalysisReport id")
        report = self.repository.get_skill_analysis_report(identifier)
        if report is None:
            raise SkillAnalysisReportNotFound(
                f"unknown SkillAnalysisReport: {identifier}"
            )
        return report

    def list_reports(
        self, target_descriptor_sha256: str, limit: int = 50
    ) -> tuple[SkillAnalysisReport, ...]:
        descriptor = self._target(target_descriptor_sha256)
        return tuple(
            self.repository.list_skill_analysis_reports(
                descriptor.content_sha256,
                limit,
            )
        )

    def record_review(
        self,
        report_id: str,
        finding_id: str,
        decision: ReviewDecision,
        reviewer_id: str,
        comment: str | None = None,
    ) -> SkillAnalysisReview:
        report = self.get_report(report_id)
        finding_identifier = require_non_blank(
            finding_id, "SkillAnalysisFinding id"
        )
        if all(
            finding.id != finding_identifier for finding in report.findings
        ):
            raise SkillAnalysisFindingNotFound(
                f"unknown SkillAnalysisFinding: {finding_identifier}"
            )
        review = SkillAnalysisReview(
            finding_id=finding_identifier,
            decision=decision,
            reviewer_id=reviewer_id,
            comment=comment,
        )
        self.repository.save_skill_analysis_review(report.id, review)
        return review

    def list_reviews(
        self, report_id: str
    ) -> tuple[SkillAnalysisReview, ...]:
        report = self.get_report(report_id)
        return tuple(self.repository.list_skill_analysis_reviews(report.id))

    def _target(self, descriptor_sha256: str) -> TargetDescriptor:
        descriptor_hash = require_sha256(
            descriptor_sha256, "Target descriptor_sha256"
        )
        descriptor = self.repository.get_target_descriptor(descriptor_hash)
        if descriptor is None:
            raise SkillAnalysisTargetNotFound(
                f"unknown TargetDescriptor: {descriptor_hash}"
            )
        return descriptor


__all__ = [
    "SkillAnalysis",
    "SkillAnalysisFindingNotFound",
    "SkillAnalysisReportNotFound",
    "SkillAnalysisTargetNotFound",
    "SkillAnalysisUnavailable",
    "SkillAnalyzer",
]
