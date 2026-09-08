from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentgate.domain import (
    CombinationPolicy,
    Evaluator,
    EvaluatorDraft,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
    EvaluatorSource,
    EvaluatorSpec,
)


def spec(**overrides: object) -> EvaluatorSpec:
    values: dict[str, object] = {
        "id": "final-state",
        "name": "Final state",
        "version": "2",
        "kind": EvaluatorKind.RULE,
        "dimension": "state",
        "metric": "final_state_match",
        "severity": EvaluatorSeverity.STANDARD,
        "implementation_id": "final_state",
        "implementation_version": "3",
        "config": {"operator": "equals", "operator_version": "1"},
    }
    values.update(overrides)
    return EvaluatorSpec(**values)


def draft(**overrides: object) -> EvaluatorDraft:
    values: dict[str, object] = {
        "evaluator_id": "custom-final-state",
        "kind": EvaluatorKind.RULE,
        "dimension": "state",
        "metric": "custom_final_state_match",
        "severity": EvaluatorSeverity.STANDARD,
        "implementation_id": "final_state",
        "implementation_version": "1",
    }
    values.update(overrides)
    return EvaluatorDraft(**values)


def test_user_evaluator_defaults_to_disabled_and_is_immutable() -> None:
    evaluator = Evaluator(name="Custom final state")

    assert evaluator.source is EvaluatorSource.USER
    assert evaluator.enabled is False
    assert evaluator.created_at.tzinfo is UTC
    with pytest.raises(ValidationError, match="frozen"):
        evaluator.enabled = True  # type: ignore[misc]


def test_evaluator_rejects_invalid_identity_and_lifecycle() -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)

    with pytest.raises(ValidationError, match="name must not be blank"):
        Evaluator(name="  ")
    with pytest.raises(ValidationError, match="timezone-aware"):
        Evaluator(name="Custom", created_at=datetime(2026, 9, 8))
    with pytest.raises(ValidationError, match="must not precede"):
        Evaluator(
            name="Custom",
            created_at=now,
            updated_at=now - timedelta(seconds=1),
        )
    with pytest.raises(ValidationError, match="built-in Evaluator must be enabled"):
        Evaluator(name="Built-in", source=EvaluatorSource.BUILTIN)

    builtin = Evaluator(
        id="final-output",
        name="Final output",
        source=EvaluatorSource.BUILTIN,
        enabled=True,
    )
    assert builtin.source is EvaluatorSource.BUILTIN


def test_evaluator_draft_is_complete_immutable_configuration() -> None:
    value = draft(
        based_on_version="2",
        config={"threshold": 0.8, "labels": ["state"]},
    )

    assert value.based_on_version == "2"
    assert value.config["labels"] == ("state",)
    assert value.model_dump(mode="json")["config"]["labels"] == ["state"]
    with pytest.raises(TypeError):
        value.config["threshold"] = 0.5  # type: ignore[index]


def test_evaluator_draft_rejects_invalid_identity_and_timestamps() -> None:
    now = datetime(2026, 9, 8, tzinfo=UTC)

    with pytest.raises(ValidationError, match="evaluator_id must not be blank"):
        draft(evaluator_id=" ")
    with pytest.raises(ValidationError, match="based_on_version must not be blank"):
        draft(based_on_version=" ")
    with pytest.raises(ValidationError, match="must not precede"):
        draft(created_at=now, updated_at=now - timedelta(seconds=1))


def test_evaluator_draft_reuses_definition_invariants() -> None:
    with pytest.raises(ValidationError, match="credential-like"):
        draft(config={"model": {"api_key": "secret"}})
    with pytest.raises(ValidationError, match="requires a model object"):
        draft(kind=EvaluatorKind.LLM_JUDGE)
    with pytest.raises(ValidationError, match="at least two"):
        draft(
            kind=EvaluatorKind.HYBRID,
            implementation_id="hybrid",
            children=(
                EvaluatorRef(evaluator_id="rule", evaluator_version="1"),
            ),
            combination=CombinationPolicy.ALL,
        )

    judge = draft(
        kind=EvaluatorKind.LLM_JUDGE,
        implementation_id="answer_quality",
        config={
            "model": {
                "provider_id": "configured-provider",
                "model_id": "judge-v1",
                "credential_ref": "configured-key",
            }
        },
    )
    assert judge.config["model"]["credential_ref"] == "configured-key"


def test_rule_spec_has_stable_hash_and_immutable_config() -> None:
    first = spec(config={"threshold": 0.8, "labels": ["state"]})
    second = spec(config={"labels": ["state"], "threshold": 0.8})

    assert first.content_sha256 == second.content_sha256
    assert first.config["labels"] == ("state",)
    with pytest.raises(TypeError):
        first.config["threshold"] = 0.5  # type: ignore[index]


def test_non_hybrid_rejects_composition() -> None:
    child = EvaluatorRef(evaluator_id="rule", evaluator_version="1")

    with pytest.raises(ValidationError, match="non-Hybrid"):
        spec(children=(child,), combination=CombinationPolicy.ALL)


def test_hybrid_composes_exact_child_versions() -> None:
    value = spec(
        kind=EvaluatorKind.HYBRID,
        implementation_id="hybrid",
        children=(
            EvaluatorRef(evaluator_id="rule", evaluator_version="1"),
            EvaluatorRef(evaluator_id="judge", evaluator_version="4"),
        ),
        combination=CombinationPolicy.ALL,
    )

    assert value.children[1].evaluator_version == "4"


def test_hybrid_requires_two_unique_children() -> None:
    child = EvaluatorRef(evaluator_id="rule", evaluator_version="1")

    with pytest.raises(ValidationError, match="at least two"):
        spec(
            kind=EvaluatorKind.HYBRID,
            implementation_id="hybrid",
            children=(child,),
            combination=CombinationPolicy.ALL,
        )
    with pytest.raises(ValidationError, match="unique"):
        spec(
            kind=EvaluatorKind.HYBRID,
            implementation_id="hybrid",
            children=(child, child),
            combination=CombinationPolicy.ALL,
        )


def test_weighted_policy_requires_only_positive_complete_weights() -> None:
    unweighted = EvaluatorRef(evaluator_id="rule", evaluator_version="1")
    weighted = EvaluatorRef(evaluator_id="judge", evaluator_version="1", weight=0.4)

    with pytest.raises(ValidationError, match="every child"):
        spec(
            kind=EvaluatorKind.HYBRID,
            implementation_id="hybrid",
            children=(unweighted, weighted),
            combination=CombinationPolicy.WEIGHTED_SCORE,
        )
    with pytest.raises(ValidationError, match="only weighted_score"):
        spec(
            kind=EvaluatorKind.HYBRID,
            implementation_id="hybrid",
            children=(
                EvaluatorRef(evaluator_id="rule", evaluator_version="1", weight=0.6),
                weighted,
            ),
            combination=CombinationPolicy.ALL,
        )


def test_llm_judge_requires_explicit_provider_and_model():
    with pytest.raises(ValidationError, match="requires a model object"):
        spec(kind=EvaluatorKind.LLM_JUDGE, config={})
    with pytest.raises(ValidationError, match="model.provider_id"):
        spec(
            kind=EvaluatorKind.LLM_JUDGE,
            config={"model": {"model_id": "judge-v1"}},
        )
    with pytest.raises(ValidationError, match="model.model_id"):
        spec(
            kind=EvaluatorKind.LLM_JUDGE,
            config={"model": {"provider_id": "public-provider"}},
        )

    value = spec(
        kind=EvaluatorKind.LLM_JUDGE,
        config={
            "model": {
                "provider_id": "private-provider",
                "model_id": "judge-v1",
                "credential_ref": "customer-key-7",
            }
        },
    )
    assert value.config["model"]["model_id"] == "judge-v1"


def test_config_rejects_plaintext_credentials_but_accepts_reference() -> None:
    with pytest.raises(ValidationError, match="credential-like"):
        spec(config={"model": {"api_key": "secret"}})

    value = spec(config={"model": {"credential_ref": "customer-key-7"}})
    assert value.config["model"]["credential_ref"] == "customer-key-7"



def test_hash_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="content hash mismatch"):
        spec(content_sha256="f" * 64)
