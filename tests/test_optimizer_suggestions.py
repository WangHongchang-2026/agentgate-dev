import pytest

from agentgate.domain import (
    EvaluatorSeverity,
    FailedResultEvidence,
    FailureCluster,
    FailureStage,
    FindingSeverity,
    RootCauseHypothesis,
    SkillAnalysisFinding,
    SuggestionPriority,
)
from agentgate.optimizer.suggestions import build_optimization_suggestions


TRACE_ID = "a" * 32
SPAN_ID = "b" * 16


def cluster(
    cluster_id: str,
    stage: FailureStage,
    *,
    share: float = 0.2,
    severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD,
    result_id: str | None = None,
) -> FailureCluster:
    resolved_result_id = result_id or f"result-{cluster_id}"
    member = FailedResultEvidence(
        run_id="run-1",
        case_id=f"case-{cluster_id}",
        result_id=resolved_result_id,
        trace_id=TRACE_ID,
        evaluator_id="evaluator",
        dimension="dimension",
        metric="metric",
        severity=severity,
        failure_stage=stage,
        reason="failed",
        span_ids=(SPAN_ID,),
    )
    return FailureCluster(
        id=cluster_id,
        category=stage.value,
        label="Failure",
        failure_stage=stage,
        evaluator_id="evaluator",
        dimension="dimension",
        metric="metric",
        severity=severity,
        members=(member,),
        representative_result_ids=(resolved_result_id,),
        failure_count=1,
        case_count=1,
        share=share,
    )


def hypothesis(
    hypothesis_id: str,
    *clusters: FailureCluster,
    confidence: float = 0.6,
    static_finding_ids: tuple[str, ...] = (),
) -> RootCauseHypothesis:
    return RootCauseHypothesis(
        id=hypothesis_id,
        category="possible_failure",
        title="Possible failure pattern",
        explanation="Hypothesis: evidence supports review.",
        confidence=confidence,
        cluster_ids=tuple(item.id for item in clusters),
        result_ids=tuple(
            member.result_id for item in clusters for member in item.members
        ),
        span_ids=(SPAN_ID,),
        static_finding_ids=static_finding_ids,
    )


def finding(finding_id: str, *skill_ids: str) -> SkillAnalysisFinding:
    return SkillAnalysisFinding(
        id=finding_id,
        check_id="skill_relationships.llm_pairwise",
        category="skill_confusion",
        severity=FindingSeverity.HIGH,
        confidence=0.8,
        skill_ids=skill_ids,
        reason="overlap",
        evidence=({"source": "test"},),
    )


@pytest.mark.parametrize(
    ("stage", "target"),
    (
        (FailureStage.TASK_UNDERSTANDING, "agent_prompt"),
        (FailureStage.PLANNING, "agent_prompt"),
        (FailureStage.RESULT_INTERPRETATION, "agent_prompt"),
        (FailureStage.FINAL_OUTPUT, "agent_prompt"),
        (FailureStage.CONTEXT_RETRIEVAL, "retrieval_configuration"),
        (FailureStage.TOOL_SELECTION, "tool_configuration"),
        (FailureStage.TOOL_ARGUMENTS, "tool_configuration"),
        (FailureStage.TOOL_EXECUTION, "tool_configuration"),
        (FailureStage.FINAL_STATE, "state_management"),
    ),
)
def test_maps_failure_stages_to_actionable_targets(
    stage: FailureStage,
    target: str,
) -> None:
    failure_cluster = cluster("cluster-1", stage)
    root_cause = hypothesis("hypothesis-1", failure_cluster)

    suggestion = build_optimization_suggestions(
        (root_cause,),
        (failure_cluster,),
    )[0]

    assert suggestion.target == target
    assert suggestion.target_id is None
    assert suggestion.requires_human_review is True


def test_routing_static_evidence_selects_one_or_multiple_skill_targets() -> None:
    route_cluster = cluster("cluster-routing", FailureStage.ROUTING)
    single_finding = finding("finding-single", "loan")
    pair_finding = finding("finding-pair", "loan", "card")

    single = build_optimization_suggestions(
        (
            hypothesis(
                "hypothesis-single",
                route_cluster,
                static_finding_ids=(single_finding.id,),
            ),
        ),
        (route_cluster,),
        (single_finding,),
    )[0]
    multiple = build_optimization_suggestions(
        (
            hypothesis(
                "hypothesis-pair",
                route_cluster,
                static_finding_ids=(pair_finding.id,),
            ),
        ),
        (route_cluster,),
        (pair_finding,),
    )[0]

    assert (single.target, single.target_id) == ("skill_description", "loan")
    assert (multiple.target, multiple.target_id) == ("skill_routing", None)


def test_routing_without_static_evidence_targets_agent_routing() -> None:
    route_cluster = cluster("cluster-routing", FailureStage.ROUTING)
    suggestion = build_optimization_suggestions(
        (hypothesis("hypothesis-1", route_cluster),),
        (route_cluster,),
    )[0]

    assert suggestion.target == "agent_routing"


@pytest.mark.parametrize(
    ("severity", "confidence", "share", "priority"),
    (
        (EvaluatorSeverity.BLOCKING, 0.75, 0.1, SuggestionPriority.CRITICAL),
        (EvaluatorSeverity.BLOCKING, 0.4, 0.1, SuggestionPriority.HIGH),
        (EvaluatorSeverity.STANDARD, 0.7, 0.1, SuggestionPriority.HIGH),
        (EvaluatorSeverity.STANDARD, 0.4, 0.5, SuggestionPriority.HIGH),
        (EvaluatorSeverity.STANDARD, 0.5, 0.1, SuggestionPriority.MEDIUM),
        (EvaluatorSeverity.STANDARD, 0.4, 0.25, SuggestionPriority.MEDIUM),
        (EvaluatorSeverity.STANDARD, 0.4, 0.1, SuggestionPriority.LOW),
    ),
)
def test_assigns_priority_from_severity_confidence_and_share(
    severity: EvaluatorSeverity,
    confidence: float,
    share: float,
    priority: SuggestionPriority,
) -> None:
    failure_cluster = cluster(
        "cluster-1",
        FailureStage.FINAL_OUTPUT,
        severity=severity,
        share=share,
    )
    suggestion = build_optimization_suggestions(
        (hypothesis("hypothesis-1", failure_cluster, confidence=confidence),),
        (failure_cluster,),
    )[0]

    assert suggestion.priority == priority


def test_mixed_failure_stages_use_generic_configuration_target() -> None:
    prompt_cluster = cluster("cluster-prompt", FailureStage.PLANNING)
    tool_cluster = cluster("cluster-tool", FailureStage.TOOL_EXECUTION)
    root_cause = hypothesis("hypothesis-1", prompt_cluster, tool_cluster)

    suggestion = build_optimization_suggestions(
        (root_cause,),
        (tool_cluster, prompt_cluster),
    )[0]

    assert suggestion.target == "agent_configuration"


def test_rationale_and_id_are_stable_and_output_is_priority_ordered() -> None:
    low_cluster = cluster("cluster-low", FailureStage.FINAL_OUTPUT, share=0.1)
    high_cluster = cluster(
        "cluster-high",
        FailureStage.FINAL_STATE,
        severity=EvaluatorSeverity.BLOCKING,
        share=0.1,
    )
    low = hypothesis("hypothesis-low", low_cluster, confidence=0.4)
    high = hypothesis("hypothesis-high", high_cluster, confidence=0.4)

    forward = build_optimization_suggestions(
        (low, high),
        (low_cluster, high_cluster),
    )
    reverse = build_optimization_suggestions(
        (high, low),
        (high_cluster, low_cluster),
    )

    assert forward == reverse
    assert forward[0].priority == SuggestionPriority.HIGH
    assert forward[1].priority == SuggestionPriority.LOW
    assert forward[0].id.startswith("optimization-suggestion-")
    assert "1 failed Results across 1 Cases" in forward[0].rationale
    assert "evidence-strength confidence 0.40" in forward[0].rationale


def test_empty_hypotheses_return_no_suggestions() -> None:
    assert build_optimization_suggestions((), ()) == ()


def test_rejects_duplicate_and_unknown_references() -> None:
    failure_cluster = cluster("cluster-1", FailureStage.FINAL_OUTPUT)
    root_cause = hypothesis("hypothesis-1", failure_cluster)
    static_finding = finding("finding-1", "loan")

    with pytest.raises(ValueError, match="hypothesis IDs must be unique"):
        build_optimization_suggestions(
            (root_cause, root_cause),
            (failure_cluster,),
        )
    with pytest.raises(ValueError, match="cluster IDs must be unique"):
        build_optimization_suggestions(
            (root_cause,),
            (failure_cluster, failure_cluster),
        )
    with pytest.raises(ValueError, match="static finding IDs must be unique"):
        build_optimization_suggestions(
            (root_cause,),
            (failure_cluster,),
            (static_finding, static_finding),
        )
    unknown_cluster = root_cause.model_copy(
        update={"cluster_ids": ("cluster-unknown",)}
    )
    with pytest.raises(ValueError, match="unknown failure cluster"):
        build_optimization_suggestions(
            (unknown_cluster,),
            (failure_cluster,),
        )
    unknown_finding = root_cause.model_copy(
        update={"static_finding_ids": ("finding-unknown",)}
    )
    with pytest.raises(ValueError, match="unknown static finding"):
        build_optimization_suggestions(
            (unknown_finding,),
            (failure_cluster,),
        )
