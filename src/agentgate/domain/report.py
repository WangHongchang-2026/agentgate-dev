"""Complete API-facing run report."""

from __future__ import annotations

from .base import DomainModel
from .gate import GateDecision
from .metric import MetricSummary
from .result import EvaluationResult
from .run import EvaluationRun


class RunReport(DomainModel):
    run: EvaluationRun
    results: tuple[EvaluationResult, ...]
    metrics: tuple[MetricSummary, ...]
    gate: GateDecision
