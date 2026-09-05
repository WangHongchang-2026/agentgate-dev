"""Assemble a validated EvaluationReport from persisted Run results."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import EvaluationReport, EvaluationResult, EvaluationRun

from .metrics import calculate_metrics
from .gate import decide_release_gate


def build_evaluation_report(
    run: EvaluationRun,
    results: Sequence[EvaluationResult],
) -> EvaluationReport:
    manifest = run.manifest
    result_list = list(results)
    metrics = calculate_metrics(
        result_list,
        manifest.primary_evaluator_ids,
        manifest.metric_plan,
    )
    release_gate = decide_release_gate(
        result_list,
        metrics,
        tuple(item.id for item in manifest.dataset.cases),
        manifest.primary_evaluator_ids,
        manifest.gate_spec,
    )
    return EvaluationReport(
        run=run,
        results=tuple(result_list),
        metrics=metrics,
        release_gate=release_gate,
    )
