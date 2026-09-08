from datetime import UTC, datetime, timedelta

import pytest

from agentgate.domain import (
    CombinationPolicy,
    Evaluator,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
    EvaluatorSource,
    EvaluatorSpec,
)
from agentgate.evaluator.versioning import (
    clone_evaluator_version_to_draft,
    create_evaluator_draft,
    publish_evaluator_draft,
    replace_evaluator_draft,
)


NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def user_evaluator(**overrides: object) -> Evaluator:
    values: dict[str, object] = {
        "id": "custom-output",
        "name": "Custom output",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return Evaluator(**values)


def create_draft(evaluator: Evaluator | None = None, **overrides: object):
    values: dict[str, object] = {
        "kind": EvaluatorKind.RULE,
        "dimension": "answer",
        "metric": "custom_output_match",
        "severity": EvaluatorSeverity.STANDARD,
        "implementation_id": "final_output",
        "implementation_version": "1",
        "config": {"mode": "strict"},
        "children": (),
        "combination": None,
    }
    values.update(overrides)
    return create_evaluator_draft(
        evaluator or user_evaluator(),
        "draft-1",
        NOW,
        **values,
    )


def test_create_draft_uses_explicit_identity_time_and_complete_body() -> None:
    draft = create_draft()

    assert draft.id == "draft-1"
    assert draft.evaluator_id == "custom-output"
    assert draft.based_on_version is None
    assert draft.created_at == NOW
    assert draft.updated_at == NOW
    assert draft.config["mode"] == "strict"


def test_create_draft_requires_user_identity_and_non_regressing_time() -> None:
    builtin = user_evaluator(
        source=EvaluatorSource.BUILTIN,
        enabled=True,
    )

    with pytest.raises(ValueError, match="requires a user Evaluator"):
        create_draft(builtin)
    with pytest.raises(ValueError, match="cannot precede"):
        create_evaluator_draft(
            user_evaluator(),
            "draft-1",
            NOW - timedelta(seconds=1),
            kind=EvaluatorKind.RULE,
            dimension="answer",
            metric="custom_output_match",
            severity=EvaluatorSeverity.STANDARD,
            implementation_id="final_output",
            implementation_version="1",
            config={},
            children=(),
            combination=None,
        )


def test_clone_exact_publication_to_draft() -> None:
    evaluator = user_evaluator()
    base = EvaluatorSpec(
        id=evaluator.id,
        name="Old display name",
        version="3",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="custom_output_match",
        severity=EvaluatorSeverity.BLOCKING,
        implementation_id="final_output",
        implementation_version="2",
        config={"mode": "lenient"},
    )

    draft = clone_evaluator_version_to_draft(
        evaluator,
        base,
        "draft-2",
        NOW + timedelta(seconds=1),
    )

    assert draft.based_on_version == "3"
    assert draft.severity is EvaluatorSeverity.BLOCKING
    assert draft.implementation_version == "2"
    assert draft.config == base.config


def test_clone_rejects_publication_from_another_evaluator() -> None:
    base = EvaluatorSpec(
        id="another-evaluator",
        name="Another",
        dimension="answer",
        metric="another_metric",
        implementation_id="final_output",
    )

    with pytest.raises(ValueError, match="belongs to another Evaluator"):
        clone_evaluator_version_to_draft(
            user_evaluator(),
            base,
            "draft-2",
            NOW,
        )


def test_replace_draft_preserves_identity_and_base_without_mutating_source() -> None:
    evaluator = user_evaluator()
    base = EvaluatorSpec(
        id=evaluator.id,
        name=evaluator.name,
        version="2",
        dimension="answer",
        metric="custom_output_match",
        implementation_id="final_output",
    )
    original = clone_evaluator_version_to_draft(
        evaluator,
        base,
        "draft-2",
        NOW,
    )
    update_time = NOW + timedelta(minutes=1)

    updated = replace_evaluator_draft(
        original,
        update_time,
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="strict_output_match",
        severity=EvaluatorSeverity.BLOCKING,
        implementation_id="final_output",
        implementation_version="2",
        config={"mode": "strict"},
        children=(),
        combination=None,
    )

    assert updated.id == original.id
    assert updated.evaluator_id == original.evaluator_id
    assert updated.created_at == original.created_at
    assert updated.based_on_version == "2"
    assert updated.updated_at == update_time
    assert updated.metric == "strict_output_match"
    assert original.metric == "custom_output_match"

    with pytest.raises(ValueError, match="must not precede"):
        replace_evaluator_draft(
            updated,
            NOW,
            kind=updated.kind,
            dimension=updated.dimension,
            metric=updated.metric,
            severity=updated.severity,
            implementation_id=updated.implementation_id,
            implementation_version=updated.implementation_version,
            config=updated.config,
            children=updated.children,
            combination=updated.combination,
        )


def test_publish_builds_hashed_spec_from_current_identity_and_draft() -> None:
    evaluator = user_evaluator(name="Current display name")
    draft = create_draft(evaluator)

    published = publish_evaluator_draft(evaluator, draft, 4)

    assert published.id == evaluator.id
    assert published.name == "Current display name"
    assert published.version == "4"
    assert published.metric == draft.metric
    assert len(published.content_sha256) == 64
    assert draft.based_on_version is None


def test_publish_rejects_wrong_owner_builtin_and_invalid_version() -> None:
    evaluator = user_evaluator()
    draft = create_draft(evaluator)
    another = user_evaluator(id="another-evaluator")
    builtin = user_evaluator(
        source=EvaluatorSource.BUILTIN,
        enabled=True,
    )

    with pytest.raises(ValueError, match="belongs to another Evaluator"):
        publish_evaluator_draft(another, draft, 1)
    with pytest.raises(ValueError, match="requires a user Evaluator"):
        publish_evaluator_draft(builtin, draft, 1)
    for invalid in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            publish_evaluator_draft(evaluator, draft, invalid)


def test_versioning_preserves_hybrid_composition() -> None:
    evaluator = user_evaluator()
    children = (
        EvaluatorRef(evaluator_id="rule", evaluator_version="1"),
        EvaluatorRef(evaluator_id="judge", evaluator_version="2"),
    )
    draft = create_draft(
        evaluator,
        kind=EvaluatorKind.HYBRID,
        implementation_id="hybrid",
        children=children,
        combination=CombinationPolicy.ALL,
    )

    published = publish_evaluator_draft(evaluator, draft, 1)

    assert published.children == children
    assert published.combination is CombinationPolicy.ALL
