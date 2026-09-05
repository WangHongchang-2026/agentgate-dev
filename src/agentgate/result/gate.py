"""Apply a snapshotted GateSpec to primary evaluator Results."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from agentgate.domain import GateDecision, GateSpec, Outcome, EvaluationResult, EvaluatorSeverity


def decide_gate(
    results: list[EvaluationResult], primary_evaluator_ids: tuple[str, ...], spec: GateSpec
) -> GateDecision:
    primary = [item for item in results if item.evaluator_id in primary_evaluator_ids]
    counts = {
        "passed": sum(item.outcome == Outcome.PASS for item in primary),
        "failed": sum(item.outcome == Outcome.FAIL for item in primary),
        "reviewed": sum(item.outcome == Outcome.REVIEW for item in primary),
        "not_applicable": sum(item.outcome == Outcome.NOT_APPLICABLE for item in primary),
        "errors": sum(item.outcome == Outcome.ERROR for item in primary),
    }
    scored = [
        item for item in primary
        if item.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW)
        and item.score is not None
    ]
    by_case: dict[str, list[float]] = defaultdict(list)
    for item in scored:
        by_case[item.case_id].append(item.score)
    score = mean(mean(values) for values in by_case.values()) if by_case else None

    if counts["errors"]:
        outcome, reason = Outcome.FAIL, "评估器执行错误，发布门禁按失败关闭"
    elif any(
        item.severity == EvaluatorSeverity.BLOCKING and item.outcome == Outcome.FAIL
        for item in primary
    ):
        outcome, reason = Outcome.FAIL, "阻断级检查失败"
    elif counts["reviewed"]:
        outcome, reason = Outcome.FAIL, "存在需要人工复核的评估结果"
    elif not scored:
        outcome, reason = Outcome.FAIL, "没有可用于门禁判定的适用评估结果"
    elif score is not None and score >= spec.threshold:
        outcome, reason = Outcome.PASS, "达到发布门槛"
    else:
        outcome, reason = Outcome.FAIL, "未达到发布门槛"
    return GateDecision(
        outcome=outcome,
        score=score,
        threshold=spec.threshold,
        reason=reason,
        **counts,
    )
