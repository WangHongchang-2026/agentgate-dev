"""Application workflow for analysis of completed evaluation Runs."""

from __future__ import annotations

from agentgate.domain import (
    EvaluationRun,
    OptimizationReport,
    ReviewDecision,
    RunStatus,
    SkillAnalysisFinding,
    SkillAnalysisReport,
    SkillAnalysisStatus,
)
from agentgate.domain.base import require_non_blank
from agentgate.optimizer import build_optimization_report
from agentgate.storage.repository import AgentGateRepository


class OptimizationRunNotFound(LookupError):
    """The requested EvaluationRun does not exist."""


class OptimizationRunNotCompleted(ValueError):
    """The requested EvaluationRun has not completed successfully."""


class OptimizationSkillAnalysisReportNotFound(LookupError):
    """The explicitly requested Skill-analysis report does not exist."""


class OptimizationSkillAnalysisMismatch(ValueError):
    """The selected Skill-analysis report belongs to another Target version."""


class OptimizationSkillAnalysisNotUsable(ValueError):
    """The selected Skill-analysis report has no usable analysis output."""


class OptimizationAnalysis:
    """Load persisted evidence and invoke the pure optimizer pipeline."""

    __slots__ = ("repository",)

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def analyze_run(
        self,
        run_id: str,
        skill_analysis_report_id: str | None = None,
    ) -> OptimizationReport:
        identifier = require_non_blank(run_id, "EvaluationRun id")
        run = self.repository.get_run(identifier)
        if run is None:
            raise OptimizationRunNotFound(
                f"unknown EvaluationRun: {identifier}"
            )
        if run.status != RunStatus.COMPLETED:
            raise OptimizationRunNotCompleted(
                f"EvaluationRun is not completed: {identifier}"
            )

        findings: tuple[SkillAnalysisFinding, ...] = ()
        if skill_analysis_report_id is not None:
            report = self._skill_analysis_report(skill_analysis_report_id)
            self._validate_skill_analysis_report(run, report)
            dismissed = {
                review.finding_id
                for review in self.repository.list_skill_analysis_reviews(report.id)
                if review.decision == ReviewDecision.DISMISSED
            }
            findings = tuple(
                finding
                for finding in sorted(report.findings, key=lambda item: item.id)
                if finding.id not in dismissed
            )
        return build_optimization_report(
            run,
            self.repository.list_results(run.id),
            findings,
        )

    def _skill_analysis_report(
        self,
        report_id: str,
    ) -> SkillAnalysisReport:
        identifier = require_non_blank(report_id, "SkillAnalysisReport id")
        report = self.repository.get_skill_analysis_report(identifier)
        if report is None:
            raise OptimizationSkillAnalysisReportNotFound(
                f"unknown SkillAnalysisReport: {identifier}"
            )
        return report

    @staticmethod
    def _validate_skill_analysis_report(
        run: EvaluationRun,
        report: SkillAnalysisReport,
    ) -> None:
        if report.status == SkillAnalysisStatus.FAILED:
            raise OptimizationSkillAnalysisNotUsable(
                f"SkillAnalysisReport has no usable output: {report.id}"
            )
        if (
            report.target_ref != run.manifest.target.ref
            or report.target_descriptor_sha256
            != run.manifest.target.descriptor_sha256
        ):
            raise OptimizationSkillAnalysisMismatch(
                "SkillAnalysisReport does not match the Run Target version"
            )


__all__ = [
    "OptimizationAnalysis",
    "OptimizationRunNotCompleted",
    "OptimizationRunNotFound",
    "OptimizationSkillAnalysisMismatch",
    "OptimizationSkillAnalysisNotUsable",
    "OptimizationSkillAnalysisReportNotFound",
]
