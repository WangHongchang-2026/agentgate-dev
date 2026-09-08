"""Evidence-backed root-cause hypotheses and attribution confidence."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import (
    FailureCluster,
    FailureStage,
    ObservedRouteKind,
    RootCauseHypothesis,
    RoutingConfusionMatrix,
    RoutingObservation,
    SkillAnalysisFinding,
    content_sha256,
)


def _incorrect_routing_observations(
    cluster: FailureCluster,
    matrix: RoutingConfusionMatrix,
) -> tuple[RoutingObservation, ...]:
    if cluster.failure_stage != FailureStage.ROUTING:
        return ()
    result_ids = {member.result_id for member in cluster.members}
    observations = (
        observation
        for cell in matrix.cells
        for observation in cell.observations
        if observation.result_id in result_ids
    )
    incorrect = (
        observation
        for observation in observations
        if observation.actual_route.kind != ObservedRouteKind.SKILL
        or observation.actual_route.skill_id != observation.expected_skill_id
    )
    return tuple(sorted(
        incorrect,
        key=lambda item: (
            item.identity,
            item.expected_skill_id,
            item.actual_route.kind.value,
            item.actual_route.skill_id or "",
        ),
    ))


def _relevant_static_findings(
    observations: tuple[RoutingObservation, ...],
    findings: tuple[SkillAnalysisFinding, ...],
) -> tuple[SkillAnalysisFinding, ...]:
    skill_ids = {observation.expected_skill_id for observation in observations}
    skill_ids.update(
        observation.actual_route.skill_id
        for observation in observations
        if observation.actual_route.kind == ObservedRouteKind.SKILL
        and observation.actual_route.skill_id is not None
    )
    return tuple(sorted(
        (
            finding
            for finding in findings
            if skill_ids.intersection(finding.skill_ids)
        ),
        key=lambda item: item.id,
    ))


def _confidence(
    cluster: FailureCluster,
    has_spans: bool,
    observations: tuple[RoutingObservation, ...],
    findings: tuple[SkillAnalysisFinding, ...],
) -> float:
    value = 0.35
    if cluster.failure_count >= 2:
        value += 0.10
    if cluster.case_count >= 2:
        value += 0.10
    if has_spans:
        value += 0.10
    if observations:
        value += 0.15
    if findings:
        value += 0.15 * max(finding.confidence for finding in findings)
    return round(min(value, 0.95), 6)


def _hypothesis_id(
    cluster: FailureCluster,
    category: str,
    result_ids: tuple[str, ...],
    span_ids: tuple[str, ...],
    observations: tuple[RoutingObservation, ...],
    finding_ids: tuple[str, ...],
) -> str:
    digest = content_sha256({
        "cluster_id": cluster.id,
        "category": category,
        "result_ids": result_ids,
        "span_ids": span_ids,
        "routing_observations": tuple(
            {
                "identity": observation.identity,
                "expected_skill_id": observation.expected_skill_id,
                "actual_route": observation.actual_route.model_dump(mode="json"),
            }
            for observation in observations
        ),
        "static_finding_ids": finding_ids,
    })
    return f"root-cause-{digest[:24]}"


def _explanation(
    cluster: FailureCluster,
    observations: tuple[RoutingObservation, ...],
    findings: tuple[SkillAnalysisFinding, ...],
) -> str:
    stage = cluster.failure_stage.value.replace("_", " ")
    text = (
        f"Hypothesis: {cluster.failure_count} failed Results across "
        f"{cluster.case_count} Cases share {stage} as the earliest observed "
        "failure stage."
    )
    if observations:
        text += (
            f" {len(observations)} incorrect routing observations show expected "
            "and actual Skill divergence."
        )
    if findings:
        text += (
            f" {len(findings)} static Skill findings involve those observed Skills."
        )
    return text


def _validate_inputs(
    clusters: tuple[FailureCluster, ...],
    findings: tuple[SkillAnalysisFinding, ...],
) -> None:
    cluster_ids = tuple(cluster.id for cluster in clusters)
    if len(set(cluster_ids)) != len(cluster_ids):
        raise ValueError("root-cause cluster IDs must be unique")
    result_ids = tuple(
        member.result_id
        for cluster in clusters
        for member in cluster.members
    )
    if len(set(result_ids)) != len(result_ids):
        raise ValueError("Results must belong to exactly one root-cause cluster")
    finding_ids = tuple(finding.id for finding in findings)
    if len(set(finding_ids)) != len(finding_ids):
        raise ValueError("root-cause static finding IDs must be unique")


def infer_root_causes(
    clusters: Sequence[FailureCluster],
    routing_matrix: RoutingConfusionMatrix,
    static_findings: Sequence[SkillAnalysisFinding] = (),
) -> tuple[RootCauseHypothesis, ...]:
    """Create one deterministic evidence-strength hypothesis per cluster."""

    cluster_items = tuple(clusters)
    finding_items = tuple(static_findings)
    _validate_inputs(cluster_items, finding_items)

    hypotheses = []
    for cluster in cluster_items:
        observations = _incorrect_routing_observations(cluster, routing_matrix)
        findings = _relevant_static_findings(observations, finding_items)
        result_ids = tuple(sorted(member.result_id for member in cluster.members))
        span_ids = tuple(sorted({
            span_id
            for member in cluster.members
            for span_id in member.span_ids
        }))
        finding_ids = tuple(finding.id for finding in findings)
        category = (
            "routing_confusion"
            if observations
            else f"{cluster.failure_stage.value}_failure"
        )
        title = (
            "Possible Skill-routing confusion"
            if observations
            else (
                "Possible "
                f"{cluster.failure_stage.value.replace('_', ' ')} failure pattern"
            )
        )
        hypotheses.append(RootCauseHypothesis(
            id=_hypothesis_id(
                cluster,
                category,
                result_ids,
                span_ids,
                observations,
                finding_ids,
            ),
            category=category,
            title=title,
            explanation=_explanation(cluster, observations, findings),
            confidence=_confidence(
                cluster,
                bool(span_ids),
                observations,
                findings,
            ),
            cluster_ids=(cluster.id,),
            result_ids=result_ids,
            span_ids=span_ids,
            static_finding_ids=finding_ids,
        ))
    return tuple(sorted(
        hypotheses,
        key=lambda item: (-item.confidence, item.id),
    ))
