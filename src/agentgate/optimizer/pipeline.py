"""Pure composition of optimization analysis for one completed Run."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import (
    EvaluationResult,
    EvaluationRun,
    OptimizationReport,
    Outcome,
    RunStatus,
    SkillAnalysisFinding,
)
from agentgate.domain.base import require_non_blank

from .clustering import cluster_failed_results
from .confusion_matrix import build_routing_confusion_matrix
from .root_cause import infer_root_causes
from .suggestions import build_optimization_suggestions


ANALYZER_VERSION = "1"


def build_optimization_report(
    run: EvaluationRun,
    results: Sequence[EvaluationResult],
    static_findings: Sequence[SkillAnalysisFinding] = (),
    *,
    analyzer_version: str = ANALYZER_VERSION,
) -> OptimizationReport:
    """Compose deterministic optimizer outputs for one completed Run."""

    if run.status != RunStatus.COMPLETED:
        raise ValueError("optimization requires a completed EvaluationRun")
    analyzer_version = require_non_blank(
        analyzer_version,
        "optimizer analyzer_version",
    )

    result_items = tuple(results)
    if any(result.run_id != run.id for result in result_items):
        raise ValueError("optimization Results must belong to the requested Run")
    finding_items = tuple(static_findings)
    dataset = run.manifest.dataset
    if dataset.version is None:
        raise ValueError("optimization requires a published Dataset version")

    failed_results = tuple(
        result for result in result_items if result.outcome == Outcome.FAIL
    )
    clusters = cluster_failed_results(failed_results)
    confusion_matrix = build_routing_confusion_matrix(
        dataset.cases,
        result_items,
    )
    hypotheses = infer_root_causes(
        clusters,
        confusion_matrix,
        finding_items,
    )
    suggestions = build_optimization_suggestions(
        hypotheses,
        clusters,
        finding_items,
    )
    return OptimizationReport(
        run_id=run.id,
        target_ref=run.manifest.target.ref,
        target_content_sha256=run.manifest.target.content_sha256,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_content_sha256=dataset.content_sha256,
        analyzer_version=analyzer_version,
        failed_result_count=len(failed_results),
        clusters=clusters,
        confusion_matrix=confusion_matrix,
        hypotheses=hypotheses,
        suggestions=suggestions,
    )
