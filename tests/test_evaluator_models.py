import pytest
from pydantic import ValidationError

from agentgate.domain.evaluator import (
    CombinationPolicy,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
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


def test_config_rejects_plaintext_credentials_but_accepts_reference() -> None:
    with pytest.raises(ValidationError, match="credential-like"):
        spec(config={"model": {"api_key": "secret"}})

    value = spec(config={"model": {"credential_ref": "customer-key-7"}})
    assert value.config["model"]["credential_ref"] == "customer-key-7"



def test_hash_mismatch_is_rejected() -> None:
    with pytest.raises(ValidationError, match="content hash mismatch"):
        spec(content_sha256="f" * 64)
