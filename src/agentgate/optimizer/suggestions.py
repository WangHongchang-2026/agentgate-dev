"""Prioritized, reviewable optimization suggestions."""

from __future__ import annotations

from collections.abc import Sequence

from agentgate.domain import (
    EvaluatorSeverity,
    FailureCluster,
    FailureStage,
    OptimizationSuggestion,
    RootCauseHypothesis,
    SkillAnalysisFinding,
    SuggestionPriority,
    content_sha256,
)


_PROMPT_STAGES = {
    FailureStage.TASK_UNDERSTANDING,
    FailureStage.PLANNING,
    FailureStage.RESULT_INTERPRETATION,
    FailureStage.FINAL_OUTPUT,
}
_TOOL_STAGES = {
    FailureStage.TOOL_SELECTION,
    FailureStage.TOOL_ARGUMENTS,
    FailureStage.TOOL_EXECUTION,
}
_PRIORITY_ORDER = {
    SuggestionPriority.CRITICAL: 0,
    SuggestionPriority.HIGH: 1,
    SuggestionPriority.MEDIUM: 2,
    SuggestionPriority.LOW: 3,
}


def _validate_inputs(
    hypotheses: tuple[RootCauseHypothesis, ...],
    clusters: tuple[FailureCluster, ...],
    findings: tuple[SkillAnalysisFinding, ...],
) -> tuple[dict[str, FailureCluster], dict[str, SkillAnalysisFinding]]:
    hypothesis_ids = tuple(item.id for item in hypotheses)
    if len(set(hypothesis_ids)) != len(hypothesis_ids):
        raise ValueError("optimization hypothesis IDs must be unique")
    cluster_ids = tuple(item.id for item in clusters)
    if len(set(cluster_ids)) != len(cluster_ids):
        raise ValueError("optimization cluster IDs must be unique")
    finding_ids = tuple(item.id for item in findings)
    if len(set(finding_ids)) != len(finding_ids):
        raise ValueError("optimization static finding IDs must be unique")

    cluster_by_id = {cluster.id: cluster for cluster in clusters}
    finding_by_id = {finding.id: finding for finding in findings}
    for hypothesis in hypotheses:
        unknown_clusters = set(hypothesis.cluster_ids).difference(cluster_by_id)
        if unknown_clusters:
            raise ValueError("hypothesis references an unknown failure cluster")
        supporting_results = {
            member.result_id
            for cluster_id in hypothesis.cluster_ids
            for member in cluster_by_id[cluster_id].members
        }
        if not set(hypothesis.result_ids).issubset(supporting_results):
            raise ValueError("hypothesis references a Result outside its clusters")
        if not set(hypothesis.static_finding_ids).issubset(finding_by_id):
            raise ValueError("hypothesis references an unknown static finding")
    return cluster_by_id, finding_by_id


def _target(
    clusters: tuple[FailureCluster, ...],
    findings: tuple[SkillAnalysisFinding, ...],
) -> tuple[str, str | None]:
    stages = {cluster.failure_stage for cluster in clusters}
    if stages == {FailureStage.ROUTING}:
        skill_ids = sorted({
            skill_id
            for finding in findings
            for skill_id in finding.skill_ids
        })
        if len(skill_ids) == 1:
            return "skill_description", skill_ids[0]
        if len(skill_ids) > 1:
            return "skill_routing", None
        return "agent_routing", None
    if len(stages) != 1:
        return "agent_configuration", None
    stage = next(iter(stages))
    if stage in _PROMPT_STAGES:
        return "agent_prompt", None
    if stage == FailureStage.CONTEXT_RETRIEVAL:
        return "retrieval_configuration", None
    if stage in _TOOL_STAGES:
        return "tool_configuration", None
    if stage == FailureStage.FINAL_STATE:
        return "state_management", None
    return "agent_configuration", None


def _priority(
    hypothesis: RootCauseHypothesis,
    clusters: tuple[FailureCluster, ...],
) -> SuggestionPriority:
    blocking = any(
        cluster.severity == EvaluatorSeverity.BLOCKING for cluster in clusters
    )
    affected_share = min(sum(cluster.share for cluster in clusters), 1.0)
    if blocking and hypothesis.confidence >= 0.75:
        return SuggestionPriority.CRITICAL
    if blocking or hypothesis.confidence >= 0.70 or affected_share >= 0.50:
        return SuggestionPriority.HIGH
    if hypothesis.confidence >= 0.50 or affected_share >= 0.25:
        return SuggestionPriority.MEDIUM
    return SuggestionPriority.LOW


def _content(
    target: str,
    target_id: str | None,
    clusters: tuple[FailureCluster, ...],
) -> tuple[str, str]:
    stage_names = sorted({
        cluster.failure_stage.value.replace("_", " ")
        for cluster in clusters
    })
    stage_text = ", ".join(stage_names)
    if target == "skill_description":
        title = f"Clarify Skill routing boundaries for {target_id}"
        recommendation = (
            f"Review and clarify the description and routing boundaries for Skill "
            f"{target_id}, then rerun the affected Cases."
        )
    elif target == "skill_routing":
        title = "Separate overlapping Skill routes"
        recommendation = (
            "Review the implicated Skill descriptions and make their routing "
            "boundaries mutually exclusive, then rerun the affected Cases."
        )
    elif target == "agent_routing":
        title = "Correct Agent routing behavior"
        recommendation = (
            "Review the Agent routing prompt and decision logic for the cited "
            "expected-versus-observed Skill mismatches, then rerun the affected Cases."
        )
    elif target == "agent_prompt":
        title = f"Strengthen Agent instructions for {stage_text}"
        recommendation = (
            f"Review the Agent prompt instructions governing {stage_text}, make the "
            "expected behavior explicit, then rerun the affected Cases."
        )
    elif target == "retrieval_configuration":
        title = "Correct context retrieval behavior"
        recommendation = (
            "Review retrieval sources, selection rules, and context assembly for the "
            "cited failures, then rerun the affected Cases."
        )
    elif target == "tool_configuration":
        title = "Correct Agent Tool behavior"
        recommendation = (
            "Review Tool selection, argument construction, and execution handling for "
            "the cited failures, then rerun the affected Cases."
        )
    elif target == "state_management":
        title = "Correct Agent state handling"
        recommendation = (
            "Review state-transition logic and final-state requirements for the cited "
            "failures, then rerun the affected Cases."
        )
    else:
        title = "Review Agent configuration"
        recommendation = (
            "Review the Agent configuration across the cited failure stages, apply "
            "one bounded change, then rerun the affected Cases."
        )
    return title, recommendation


def _rationale(
    hypothesis: RootCauseHypothesis,
    clusters: tuple[FailureCluster, ...],
) -> str:
    result_ids = set(hypothesis.result_ids)
    case_ids = {
        member.case_id
        for cluster in clusters
        for member in cluster.members
        if member.result_id in result_ids
    }
    affected_share = min(sum(cluster.share for cluster in clusters), 1.0)
    return (
        f"{hypothesis.title} affects {len(result_ids)} failed Results across "
        f"{len(case_ids)} Cases ({affected_share:.1%} of failed Results) with "
        f"evidence-strength confidence {hypothesis.confidence:.2f}."
    )


def _suggestion_id(
    hypothesis: RootCauseHypothesis,
    target: str,
    target_id: str | None,
    priority: SuggestionPriority,
    recommendation: str,
) -> str:
    digest = content_sha256({
        "hypothesis_id": hypothesis.id,
        "target": target,
        "target_id": target_id,
        "priority": priority,
        "recommendation": recommendation,
    })
    return f"optimization-suggestion-{digest[:24]}"


def build_optimization_suggestions(
    hypotheses: Sequence[RootCauseHypothesis],
    clusters: Sequence[FailureCluster],
    static_findings: Sequence[SkillAnalysisFinding] = (),
) -> tuple[OptimizationSuggestion, ...]:
    """Build deterministic recommendations that always require human review."""

    hypothesis_items = tuple(hypotheses)
    cluster_items = tuple(clusters)
    finding_items = tuple(static_findings)
    cluster_by_id, finding_by_id = _validate_inputs(
        hypothesis_items,
        cluster_items,
        finding_items,
    )

    ranked = []
    for hypothesis in hypothesis_items:
        supporting_clusters = tuple(
            cluster_by_id[cluster_id] for cluster_id in hypothesis.cluster_ids
        )
        supporting_findings = tuple(
            finding_by_id[finding_id]
            for finding_id in hypothesis.static_finding_ids
        )
        target, target_id = _target(supporting_clusters, supporting_findings)
        priority = _priority(hypothesis, supporting_clusters)
        title, recommendation = _content(target, target_id, supporting_clusters)
        suggestion = OptimizationSuggestion(
            id=_suggestion_id(
                hypothesis,
                target,
                target_id,
                priority,
                recommendation,
            ),
            target=target,
            target_id=target_id,
            priority=priority,
            title=title,
            recommendation=recommendation,
            rationale=_rationale(hypothesis, supporting_clusters),
            hypothesis_ids=(hypothesis.id,),
            requires_human_review=True,
        )
        ranked.append((suggestion, hypothesis.confidence))
    ranked.sort(key=lambda item: (
        _PRIORITY_ORDER[item[0].priority],
        -item[1],
        item[0].id,
    ))
    return tuple(item[0] for item in ranked)
