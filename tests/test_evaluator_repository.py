import sqlite3
from datetime import UTC, datetime, timedelta
from inspect import signature

import pytest

from agentgate.domain import Evaluator, EvaluatorKind, EvaluatorSeverity, EvaluatorSource
from agentgate.evaluator.versioning import (
    clone_evaluator_version_to_draft,
    create_evaluator_draft,
    publish_evaluator_draft,
    replace_evaluator_draft,
)
from agentgate.storage.repository import AgentGateRepository
from agentgate.storage.sqlite import SQLiteRepository


NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def evaluator(
    evaluator_id: str = "custom-output",
    *,
    enabled: bool = False,
    updated_at: datetime = NOW,
) -> Evaluator:
    return Evaluator(
        id=evaluator_id,
        name="Custom output",
        enabled=enabled,
        created_at=NOW,
        updated_at=updated_at,
    )


def draft_for(
    value: Evaluator,
    *,
    draft_id: str = "draft-1",
    created_at: datetime = NOW,
):
    return create_evaluator_draft(
        value,
        draft_id,
        created_at,
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="custom_output_match",
        severity=EvaluatorSeverity.STANDARD,
        implementation_id="final_output",
        implementation_version="1",
        config={"mode": "strict"},
        children=(),
        combination=None,
    )


def test_repository_protocol_exposes_evaluator_catalog_operations() -> None:
    expected_parameters = {
        "save_evaluator": ("self", "evaluator"),
        "save_evaluator_with_draft": ("self", "evaluator", "draft"),
        "get_evaluator": ("self", "evaluator_id"),
        "list_evaluators": ("self", "include_disabled"),
        "delete_unpublished_evaluator": ("self", "evaluator_id"),
        "save_evaluator_draft": ("self", "draft"),
        "get_evaluator_draft": ("self", "evaluator_id"),
        "delete_evaluator_draft": (
            "self",
            "evaluator_id",
            "expected_draft_id",
        ),
        "list_evaluator_versions": ("self", "evaluator_id"),
        "get_evaluator_version": ("self", "evaluator_id", "version"),
        "get_latest_evaluator_version": ("self", "evaluator_id"),
        "publish_evaluator_draft": (
            "self",
            "expected_draft_id",
            "published",
        ),
    }

    for method_name, parameters in expected_parameters.items():
        method = getattr(AgentGateRepository, method_name)
        assert tuple(signature(method).parameters) == parameters


def test_sqlite_initializes_evaluator_catalog_schema_idempotently(tmp_path) -> None:
    path = tmp_path / "catalog-schema.db"
    SQLiteRepository(path)
    SQLiteRepository(path)

    with sqlite3.connect(path) as db:
        tables = {
            row[0]
            for row in db.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'evaluator%'
                """
            )
        }
        assert tables == {
            "evaluators",
            "evaluator_drafts",
            "evaluator_versions",
        }
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            db.execute(
                """
                INSERT INTO evaluators(
                    id,source,enabled,created_at,updated_at,payload
                ) VALUES(?,?,?,?,?,?)
                """,
                ("builtin", "builtin", 1, NOW.isoformat(), NOW.isoformat(), "{}"),
            )


def test_evaluator_identity_round_trip_filter_and_stale_write(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "identity.db")
    original = evaluator()

    assert repository.get_evaluator(original.id) is None
    repository.save_evaluator(original)
    repository.save_evaluator(original)

    assert repository.list_evaluators() == []
    assert repository.list_evaluators(include_disabled=True) == [original]

    current = original.model_copy(
        update={
            "name": "Current output",
            "enabled": True,
            "updated_at": NOW + timedelta(seconds=2),
        }
    )
    repository.save_evaluator(current)

    assert repository.get_evaluator(original.id) == current
    assert repository.list_evaluators() == [current]

    changed_creation = current.model_copy(
        update={"created_at": NOW - timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="created_at is immutable"):
        repository.save_evaluator(changed_creation)
    with pytest.raises(ValueError, match="stale Evaluator"):
        repository.save_evaluator(original.model_copy(update={"name": "Stale"}))

    builtin = Evaluator(
        id="builtin",
        name="Built-in",
        source=EvaluatorSource.BUILTIN,
        enabled=True,
    )
    with pytest.raises(ValueError, match="only user Evaluators"):
        repository.save_evaluator(builtin)


def test_save_evaluator_with_draft_is_atomic(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "atomic-create.db")
    first = evaluator("first")
    first_draft = draft_for(first, draft_id="shared-draft")
    repository.save_evaluator_with_draft(first, first_draft)

    assert repository.get_evaluator(first.id) == first
    assert repository.get_evaluator_draft(first.id) == first_draft

    second = evaluator("second")
    second_draft = draft_for(second, draft_id="shared-draft")
    with pytest.raises(sqlite3.IntegrityError):
        repository.save_evaluator_with_draft(second, second_draft)

    assert repository.get_evaluator(second.id) is None
    assert repository.get_evaluator_draft(second.id) is None

    mismatched = evaluator("mismatched")
    with pytest.raises(ValueError, match="must belong"):
        repository.save_evaluator_with_draft(mismatched, first_draft)
    assert repository.get_evaluator(mismatched.id) is None


def test_evaluator_draft_save_is_single_owner_and_stale_safe(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "draft.db")
    value = evaluator()
    repository.save_evaluator(value)
    original = draft_for(value)
    repository.save_evaluator_draft(original)
    repository.save_evaluator_draft(original)

    current = replace_evaluator_draft(
        original,
        NOW + timedelta(seconds=2),
        kind=original.kind,
        dimension=original.dimension,
        metric="current_output_match",
        severity=original.severity,
        implementation_id=original.implementation_id,
        implementation_version=original.implementation_version,
        config=original.config,
        children=original.children,
        combination=original.combination,
    )
    repository.save_evaluator_draft(current)

    assert repository.get_evaluator_draft(value.id) == current
    with pytest.raises(ValueError, match="stale EvaluatorDraft"):
        repository.save_evaluator_draft(original)
    with pytest.raises(ValueError, match="active draft"):
        repository.save_evaluator_draft(
            draft_for(value, draft_id="another-draft")
        )
    with pytest.raises(ValueError, match="expected Evaluator draft"):
        repository.delete_evaluator_draft(value.id, "stale-draft")

    repository.delete_evaluator_draft(value.id, current.id)
    assert repository.get_evaluator_draft(value.id) is None


def test_publication_consumes_draft_and_versions_are_exactly_ordered(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "publication.db")
    value = evaluator()
    first_draft = draft_for(value)
    repository.save_evaluator_with_draft(value, first_draft)
    first = publish_evaluator_draft(value, first_draft, 1)

    repository.publish_evaluator_draft(first_draft.id, first)

    assert repository.get_evaluator_draft(value.id) is None
    assert repository.get_evaluator_version(value.id, "1") == first
    assert repository.get_latest_evaluator_version(value.id) == first
    assert repository.list_evaluator_versions(value.id) == [first]

    second_draft = clone_evaluator_version_to_draft(
        value,
        first,
        "draft-2",
        NOW + timedelta(seconds=1),
    )
    repository.save_evaluator_draft(second_draft)
    second = publish_evaluator_draft(value, second_draft, 2)
    repository.publish_evaluator_draft(second_draft.id, second)

    assert repository.list_evaluator_versions(value.id) == [second, first]
    assert repository.get_evaluator_version(value.id, "2") == second
    assert repository.get_evaluator_version(value.id, "3") is None
    with pytest.raises(ValueError, match="canonical positive integer"):
        repository.get_evaluator_version(value.id, "01")


def test_publication_rejects_skipped_version_and_changed_draft_atomically(
    tmp_path,
) -> None:
    repository = SQLiteRepository(tmp_path / "stale-publication.db")
    value = evaluator()
    original = draft_for(value)
    repository.save_evaluator_with_draft(value, original)

    skipped = publish_evaluator_draft(value, original, 2)
    with pytest.raises(ValueError, match="requires version 1"):
        repository.publish_evaluator_draft(original.id, skipped)
    assert repository.get_evaluator_draft(value.id) == original
    assert repository.list_evaluator_versions(value.id) == []

    stale_candidate = publish_evaluator_draft(value, original, 1)
    current = replace_evaluator_draft(
        original,
        NOW + timedelta(seconds=1),
        kind=original.kind,
        dimension=original.dimension,
        metric="changed_metric",
        severity=original.severity,
        implementation_id=original.implementation_id,
        implementation_version=original.implementation_version,
        config=original.config,
        children=original.children,
        combination=original.combination,
    )
    repository.save_evaluator_draft(current)

    with pytest.raises(ValueError, match="does not match the current draft"):
        repository.publish_evaluator_draft(original.id, stale_candidate)
    assert repository.get_evaluator_draft(value.id) == current
    assert repository.list_evaluator_versions(value.id) == []


def test_unpublished_delete_cascades_draft_but_preserves_publications(
    tmp_path,
) -> None:
    repository = SQLiteRepository(tmp_path / "delete.db")
    unpublished = evaluator("unpublished")
    unpublished_draft = draft_for(unpublished)
    repository.save_evaluator_with_draft(unpublished, unpublished_draft)

    repository.delete_unpublished_evaluator(unpublished.id)

    assert repository.get_evaluator(unpublished.id) is None
    assert repository.get_evaluator_draft(unpublished.id) is None
    with pytest.raises(ValueError, match="unknown Evaluator"):
        repository.delete_unpublished_evaluator(unpublished.id)

    published_identity = evaluator("published")
    published_draft = draft_for(published_identity)
    repository.save_evaluator_with_draft(published_identity, published_draft)
    published = publish_evaluator_draft(
        published_identity,
        published_draft,
        1,
    )
    repository.publish_evaluator_draft(published_draft.id, published)

    with pytest.raises(ValueError, match="published Evaluator cannot be deleted"):
        repository.delete_unpublished_evaluator(published_identity.id)
    assert repository.get_evaluator_version(published_identity.id, "1") == published


def test_version_reads_detect_corrupt_indexed_columns(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "corrupt-version.db")
    value = evaluator()
    draft = draft_for(value)
    repository.save_evaluator_with_draft(value, draft)
    published = publish_evaluator_draft(value, draft, 1)
    repository.publish_evaluator_draft(draft.id, published)

    with sqlite3.connect(repository.path) as db:
        db.execute(
            """
            UPDATE evaluator_versions
            SET content_sha256=?
            WHERE evaluator_id=? AND version=?
            """,
            ("f" * 64, value.id, 1),
        )

    with pytest.raises(ValueError, match="content hash"):
        repository.get_evaluator_version(value.id, "1")
