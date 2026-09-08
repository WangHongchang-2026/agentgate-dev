"""Deterministic grouping of failed Evaluation Results."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from agentgate.domain import (
    EvaluationResult,
    EvaluatorSeverity,
    FailedResultEvidence,
    FailureCluster,
    FailureStage,
    Outcome,
    content_sha256,
)


MAX_REPRESENTATIVES = 3

_GroupKey = tuple[FailureStage, str, str, str, EvaluatorSeverity]


def _group_key(result: EvaluationResult) -> _GroupKey:
    failure_stage = result.primary_failure_stage
    if failure_stage is None:
        raise ValueError("failed Results require primary_failure_stage")
    return (
        failure_stage,
        result.evaluator_id,
        result.dimension,
        result.metric,
        result.severity,
    )


def _evidence(result: EvaluationResult) -> FailedResultEvidence:
    span_ids = tuple(sorted({
        span_id
        for check in result.checks
        if check.outcome == Outcome.FAIL
        for span_id in check.span_ids
    }))
    return FailedResultEvidence(
        run_id=result.run_id,
        case_id=result.case_id,
        result_id=result.id,
        trace_id=result.trace_id,
        evaluator_id=result.evaluator_id,
        dimension=result.dimension,
        metric=result.metric,
        severity=result.severity,
        failure_stage=_group_key(result)[0],
        reason=result.reason,
        span_ids=span_ids,
    )


def _cluster_id(key: _GroupKey) -> str:
    failure_stage, evaluator_id, dimension, metric, severity = key
    digest = content_sha256({
        "failure_stage": failure_stage,
        "evaluator_id": evaluator_id,
        "dimension": dimension,
        "metric": metric,
        "severity": severity,
    })
    return f"failure-cluster-{digest[:24]}"


def _label(key: _GroupKey) -> str:
    failure_stage, evaluator_id, dimension, metric, _ = key
    stage_label = failure_stage.value.replace("_", " ").title()
    return f"{stage_label}: {dimension}/{metric} ({evaluator_id})"


def _cluster_sort_key(cluster: FailureCluster) -> tuple[object, ...]:
    severity_order = 0 if cluster.severity == EvaluatorSeverity.BLOCKING else 1
    return (
        -cluster.failure_count,
        severity_order,
        cluster.failure_stage.value,
        cluster.evaluator_id,
        cluster.dimension,
        cluster.metric,
        cluster.id,
    )


def cluster_failed_results(
    results: Sequence[EvaluationResult],
) -> tuple[FailureCluster, ...]:
    """Group failed Results by stable evaluation and failure dimensions."""

    items = tuple(results)
    if not items:
        return ()
    if any(result.outcome != Outcome.FAIL for result in items):
        raise ValueError("clustering accepts only failed Results")

    result_ids = tuple(result.id for result in items)
    if len(set(result_ids)) != len(result_ids):
        raise ValueError("clustering Result IDs must be unique")
    if len({result.run_id for result in items}) != 1:
        raise ValueError("clustering Results must belong to one Run")

    grouped: dict[_GroupKey, list[FailedResultEvidence]] = defaultdict(list)
    for result in items:
        grouped[_group_key(result)].append(_evidence(result))

    total = len(items)
    clusters = []
    for key, values in grouped.items():
        members = tuple(sorted(values, key=lambda item: (item.case_id, item.result_id)))
        failure_stage, evaluator_id, dimension, metric, severity = key
        clusters.append(FailureCluster(
            id=_cluster_id(key),
            category=failure_stage.value,
            label=_label(key),
            failure_stage=failure_stage,
            evaluator_id=evaluator_id,
            dimension=dimension,
            metric=metric,
            severity=severity,
            members=members,
            representative_result_ids=tuple(
                member.result_id for member in members[:MAX_REPRESENTATIVES]
            ),
            failure_count=len(members),
            case_count=len({member.case_id for member in members}),
            share=len(members) / total,
        ))
    return tuple(sorted(clusters, key=_cluster_sort_key))
