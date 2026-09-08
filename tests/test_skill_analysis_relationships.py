from __future__ import annotations

import json

import pytest

from agentgate.domain import (
    FindingSeverity,
    SkillAnalysisStatus,
    SkillDescriptor,
    TargetDescriptor,
    TargetRef,
    TargetType,
)
from agentgate.evaluator.judge.model_protocol import (
    JudgeModelTimeout,
    JudgeRequest,
    JudgeResponse,
)
from agentgate.skill_analysis import analyze_skill_relationships


def assessment(
    relationship: str = "none",
    *,
    confidence: float = 0.9,
    reason: str = "The responsibilities are separate.",
    examples: list[str] | None = None,
    suggestion: str | None = None,
) -> JudgeResponse:
    return JudgeResponse(
        text=json.dumps(
            {
                "relationship": relationship,
                "confidence": confidence,
                "reason": reason,
                "ambiguous_examples": examples or [],
                "suggestion": suggestion,
            }
        ),
        resolved_model_id="resolved-model",
    )


class RecordingModel:
    provider_id = "test-provider"

    def __init__(self, outcomes: list[JudgeResponse | Exception]) -> None:
        self.outcomes = iter(outcomes)
        self.requests: list[JudgeRequest] = []

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        self.requests.append(request)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def skill(skill_id: str, description: str | None) -> SkillDescriptor:
    return SkillDescriptor(
        external_skill_id=skill_id,
        external_version_id="1",
        name=skill_id.replace("-", " ").title(),
        description=description,
    )


def descriptor(*skills: SkillDescriptor) -> TargetDescriptor:
    return TargetDescriptor(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="agent",
            external_version_id="1",
        ),
        display_name="Demo Agent",
        skills=skills,
    )


def test_less_than_two_skills_returns_completed_empty_report() -> None:
    model = RecordingModel([])

    report = analyze_skill_relationships(
        descriptor(skill("only", "Handle one responsibility.")),
        model,
        model_id="judge-model",
    )

    assert report.status is SkillAnalysisStatus.COMPLETED
    assert report.findings == ()
    assert report.risk_matrix == ()
    assert report.errors == ()
    assert model.requests == []


def test_analyzes_pairs_in_stable_identity_order_and_redacts_descriptions() -> None:
    model = RecordingModel([assessment(), assessment(), assessment()])
    target = descriptor(
        skill("zeta", "Handle zeta requests."),
        skill("alpha", "Contact owner@example.com with api_key=secret-value"),
        skill("middle", "Handle middle requests."),
    )

    report = analyze_skill_relationships(target, model, model_id="judge-model")

    assert report.status is SkillAnalysisStatus.COMPLETED
    assert len(report.risk_matrix) == 3
    pairs = [
        (
            json.loads(request.user_prompt)["left_skill"]["id"],
            json.loads(request.user_prompt)["right_skill"]["id"],
        )
        for request in model.requests
    ]
    assert pairs == [("alpha", "middle"), ("alpha", "zeta"), ("middle", "zeta")]
    assert all("secret-value" not in request.user_prompt for request in model.requests)
    assert all("owner@example.com" not in request.user_prompt for request in model.requests)


def test_conflict_becomes_deterministic_high_severity_finding() -> None:
    model = RecordingModel(
        [
            assessment(
                "ambiguous",
                confidence=0.88,
                reason="Both Skills accept a new financing request.",
                examples=["I want financing for a home."],
                suggestion="State which financing products each Skill owns.",
            )
        ]
    )
    target = descriptor(
        skill("loan", "Handle loan applications."),
        skill("finance", "Handle financing requests."),
    )

    first = analyze_skill_relationships(target, model, model_id="judge-model")
    second_model = RecordingModel(
        [
            assessment(
                "ambiguous",
                confidence=0.88,
                reason="Both Skills accept a new financing request.",
                examples=["I want financing for a home."],
                suggestion="State which financing products each Skill owns.",
            )
        ]
    )
    second = analyze_skill_relationships(target, second_model, model_id="judge-model")

    assert len(first.findings) == 1
    finding = first.findings[0]
    assert finding.id == second.findings[0].id
    assert finding.category == "skill_confusion"
    assert finding.severity is FindingSeverity.HIGH
    assert finding.skill_ids == ("finance", "loan")
    assert finding.suggestions == (
        "State which financing products each Skill owns.",
    )
    assert finding.evidence[0]["request_sha256"]


def test_low_confidence_relationship_stays_in_matrix_without_finding() -> None:
    model = RecordingModel(
        [assessment("overlap", confidence=0.4, reason="Weak overlap evidence.")]
    )

    report = analyze_skill_relationships(
        descriptor(
            skill("one", "Handle account requests."),
            skill("two", "Handle profile requests."),
        ),
        model,
        model_id="judge-model",
        min_confidence=0.6,
    )

    assert report.status is SkillAnalysisStatus.COMPLETED
    assert report.findings == ()
    assert report.risk_matrix[0]["relationship"] == "overlap"


def test_one_failed_pair_preserves_successful_pair_as_partial_report() -> None:
    model = RecordingModel(
        [
            JudgeModelTimeout("slow"),
            assessment("none"),
            assessment("duplicate", reason="Same declared responsibility."),
        ]
    )

    report = analyze_skill_relationships(
        descriptor(
            skill("a", "Handle A."),
            skill("b", "Handle B."),
            skill("c", "Handle C."),
        ),
        model,
        model_id="judge-model",
    )

    assert report.status is SkillAnalysisStatus.PARTIAL
    assert len(report.risk_matrix) == 2
    assert len(report.findings) == 1
    assert report.errors[0]["category"] == "timeout"
    assert "slow" not in report.model_dump_json()


@pytest.mark.parametrize(
    "response",
    [
        JudgeModelTimeout("slow"),
        JudgeResponse(text="not-json", resolved_model_id="model"),
        JudgeResponse(
            text=json.dumps(
                {
                    "relationship": "unknown",
                    "confidence": 1,
                    "reason": "Unsupported relationship.",
                    "ambiguous_examples": [],
                    "suggestion": None,
                }
            ),
            resolved_model_id="model",
        ),
    ],
)
def test_total_model_failure_returns_failed_report(
    response: JudgeResponse | Exception,
) -> None:
    model = RecordingModel([response])

    report = analyze_skill_relationships(
        descriptor(
            skill("one", "Handle one."),
            skill("two", "Handle two."),
        ),
        model,
        model_id="judge-model",
    )

    assert report.status is SkillAnalysisStatus.FAILED
    assert report.findings == ()
    assert report.risk_matrix == ()
    assert len(report.errors) == 1


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"model_id": " "}, "model_id"),
        ({"min_confidence": 1.1}, "min_confidence"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"analyzer_version": ""}, "analyzer_version"),
    ],
)
def test_configuration_is_validated(changes: dict[str, object], message: str) -> None:
    arguments = {
        "model_id": "judge-model",
        "min_confidence": 0.6,
        "timeout_seconds": 60,
        "analyzer_version": "1",
    }
    arguments.update(changes)

    with pytest.raises(ValueError, match=message):
        analyze_skill_relationships(
            descriptor(),
            RecordingModel([]),
            **arguments,
        )
