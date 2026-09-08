"""Static Skill-analysis report and review endpoints."""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from agentgate.application.skill_analysis import (
    SkillAnalysisFindingNotFound,
    SkillAnalysisReportNotFound,
    SkillAnalysisTargetNotFound,
    SkillAnalysisUnavailable,
)
from agentgate.domain import (
    ReviewDecision,
    SkillAnalysisReport,
    SkillAnalysisReview,
)
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_not_found, raise_unprocessable


router = APIRouter(prefix="/api/skill-analysis", tags=["skill-analysis"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyzeTargetRequest(_RequestModel):
    target_descriptor_sha256: str


class ReviewFindingRequest(_RequestModel):
    decision: ReviewDecision
    reviewer_id: str
    comment: str | None = None


class SkillAnalysisReportDetail(BaseModel):
    report: SkillAnalysisReport
    reviews: tuple[SkillAnalysisReview, ...]


def _raise_analysis_error(error: Exception) -> NoReturn:
    if isinstance(
        error,
        (
            SkillAnalysisTargetNotFound,
            SkillAnalysisReportNotFound,
            SkillAnalysisFindingNotFound,
        ),
    ):
        raise_not_found(error)
    if isinstance(error, SkillAnalysisUnavailable):
        raise HTTPException(
            status_code=503,
            detail="Skill analysis is unavailable",
        ) from error
    raise_unprocessable(error)


@router.post("/reports", status_code=201)
def analyze_target(
    request: AnalyzeTargetRequest,
    dependencies: Dependencies,
) -> SkillAnalysisReport:
    try:
        return dependencies.skill_analysis.analyze_target(
            request.target_descriptor_sha256
        )
    except (
        SkillAnalysisTargetNotFound,
        SkillAnalysisUnavailable,
        ValueError,
    ) as error:
        _raise_analysis_error(error)


@router.get("/reports")
def list_reports(
    dependencies: Dependencies,
    target_descriptor_sha256: str,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> tuple[SkillAnalysisReport, ...]:
    try:
        return dependencies.skill_analysis.list_reports(
            target_descriptor_sha256,
            limit,
        )
    except (SkillAnalysisTargetNotFound, ValueError) as error:
        _raise_analysis_error(error)


@router.get("/reports/{report_id}")
def report_detail(
    report_id: str,
    dependencies: Dependencies,
) -> SkillAnalysisReportDetail:
    try:
        return SkillAnalysisReportDetail(
            report=dependencies.skill_analysis.get_report(report_id),
            reviews=dependencies.skill_analysis.list_reviews(report_id),
        )
    except (SkillAnalysisReportNotFound, ValueError) as error:
        _raise_analysis_error(error)


@router.put("/reports/{report_id}/findings/{finding_id}/review")
def review_finding(
    report_id: str,
    finding_id: str,
    request: ReviewFindingRequest,
    dependencies: Dependencies,
) -> SkillAnalysisReview:
    try:
        return dependencies.skill_analysis.record_review(
            report_id,
            finding_id,
            request.decision,
            request.reviewer_id,
            request.comment,
        )
    except (
        SkillAnalysisReportNotFound,
        SkillAnalysisFindingNotFound,
        ValueError,
    ) as error:
        _raise_analysis_error(error)
