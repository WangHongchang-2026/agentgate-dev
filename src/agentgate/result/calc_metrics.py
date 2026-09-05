"""Calculate report summaries from persisted evaluator Results."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from statistics import mean

from agentgate.domain import MetricPlan, MetricSummary, Outcome, EvaluationResult

LABELS = {
    "overall": "综合得分",
    "rule": "规则评估准确率",
    "llm_judge": "LLM Judge 准确率",
    "hybrid": "混合评估准确率",
    "routing": "路由准确率",
    "tool_use": "工具准确率",
    "state": "状态准确率",
    "answer": "回答准确率",
    "safety": "策略合规率",
    "efficiency": "效率",
    "skill_routing_accuracy": "技能路由正确率",
    "tool_coverage": "必需工具覆盖率",
    "forbidden_tool_compliance": "禁用工具合规率",
    "tool_argument_accuracy": "工具参数准确率",
    "final_state_match": "最终状态匹配率",
    "final_output_match": "最终输出匹配率",
    "policy_compliance": "策略合规率",
}


def _counts(results: Iterable[EvaluationResult]) -> dict[str, int | bool]:
    items = list(results)
    return {
        "passed": sum(item.outcome == Outcome.PASS for item in items),
        "failed": sum(item.outcome == Outcome.FAIL for item in items),
        "reviewed": sum(item.outcome == Outcome.REVIEW for item in items),
        "not_applicable": sum(item.outcome == Outcome.NOT_APPLICABLE for item in items),
        "errors": sum(item.outcome == Outcome.ERROR for item in items),
        "applicable": sum(
            item.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW) for item in items
        ),
        "total": len(items),
        "incomplete": any(item.outcome == Outcome.ERROR for item in items),
    }


def _metric_score(results: list[EvaluationResult]) -> float | None:
    by_case: dict[str, list[float]] = defaultdict(list)
    for result in results:
        if result.outcome in (Outcome.PASS, Outcome.FAIL, Outcome.REVIEW):
            if result.score is not None:
                by_case[result.case_id].append(result.score)
    case_scores = [mean(scores) for scores in by_case.values() if scores]
    return mean(case_scores) if case_scores else None


def _metric_summaries(results: list[EvaluationResult]) -> list[MetricSummary]:
    grouped: dict[str, list[EvaluationResult]] = defaultdict(list)
    for result in results:
        grouped[result.metric].append(result)
    return [
        MetricSummary(
            key=key,
            label=LABELS.get(key, key),
            level="metric",
            score=_metric_score(items),
            **_counts(items),
        )
        for key, items in grouped.items()
    ]


def calculate_metrics(
    results: list[EvaluationResult], primary_evaluator_ids: tuple[str, ...], plan: MetricPlan
) -> tuple[MetricSummary, ...]:
    if plan.primary_only:
        primary = [item for item in results if item.evaluator_id in primary_evaluator_ids]
    else:
        primary = list(results)

    metric_summaries = _metric_summaries(primary)
    metric_dimension = {item.metric: item.dimension for item in primary}

    dimensions: list[MetricSummary] = []
    for dimension in dict.fromkeys(metric_dimension.values()):
        children = [
            item for item in metric_summaries
            if metric_dimension.get(item.key) == dimension
        ]
        scores = [item.score for item in children if item.score is not None]
        related = [item for item in primary if item.dimension == dimension]
        dimensions.append(MetricSummary(
            key=dimension,
            label=LABELS.get(dimension, dimension),
            level="dimension",
            score=mean(scores) if scores else None,
            **_counts(related),
        ))

    kinds: list[MetricSummary] = []
    for kind in dict.fromkeys(item.evaluator_kind.value for item in primary):
        related = [item for item in primary if item.evaluator_kind.value == kind]
        filtered_metrics = _metric_summaries(related)
        scores = [item.score for item in filtered_metrics if item.score is not None]
        kinds.append(MetricSummary(
            key=kind,
            label=LABELS.get(kind, kind),
            level="kind",
            score=mean(scores) if scores else None,
            **_counts(related),
        ))

    dimension_scores = [item.score for item in dimensions if item.score is not None]
    overall = MetricSummary(
        key="overall",
        label=LABELS["overall"],
        level="overall",
        score=mean(dimension_scores) if dimension_scores else None,
        **_counts(primary),
    )
    return (overall, *kinds, *dimensions, *metric_summaries)
