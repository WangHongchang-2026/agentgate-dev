"""Construct complete reports without hidden metric or Gate defaults."""

from agentgate.domain import EvaluationResult, EvaluationRun, RunReport

from .calc_metrics import calculate_metrics
from .gate import decide_gate


def build_report(run: EvaluationRun, results: list[EvaluationResult]) -> RunReport:
    manifest = run.manifest
    metrics = calculate_metrics(
        results, manifest.primary_evaluator_ids, manifest.metric_plan
    )
    gate = decide_gate(results, manifest.primary_evaluator_ids, manifest.gate_spec)
    return RunReport(run=run, results=tuple(results), metrics=metrics, gate=gate)
