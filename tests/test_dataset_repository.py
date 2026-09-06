import sqlite3
from datetime import timedelta
from uuid import uuid4

import pytest

from agentgate.case import DatasetService
from agentgate.domain import Case, CaseTurn, DatasetVersion, DatasetVersionStatus
from agentgate.storage.sqlite import SQLiteRepository


def test_sqlite_connection_enforces_pragmas_and_closes(tmp_path):
    repository = SQLiteRepository(tmp_path / "connection.db", busy_timeout_ms=1_234)

    with repository._connect() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1_234

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_sqlite_connection_rejects_invalid_busy_timeout(tmp_path):
    with pytest.raises(ValueError, match="busy_timeout_ms"):
        SQLiteRepository(tmp_path / "connection.db", busy_timeout_ms=0)


def test_sqlite_initialization_enables_wal_and_schema_checks(tmp_path):
    repository = SQLiteRepository(tmp_path / "schema.db")

    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        connection.execute(
            "INSERT INTO datasets VALUES(?,?,?,?,?)",
            ("dataset", "Dataset", 0, "2026-09-06T00:00:00+00:00", "{}"),
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            connection.execute(
                "INSERT INTO dataset_versions VALUES(?,?,?,?,?,?,?)",
                ("draft", "dataset", 1, "draft", "now", "hash", "{}"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            connection.execute(
                "INSERT INTO runs VALUES(?,?,?,?)",
                ("run", "unknown", "now", "{}"),
            )


def test_sqlite_persists_catalog_and_enforces_one_draft(tmp_path):
    repository = SQLiteRepository(tmp_path / "repository.db")
    service = DatasetService(repository)
    dataset = service.create_dataset("Dataset")
    first = service.create_draft(dataset.id)
    with pytest.raises(ValueError, match="active draft"):
        service.create_draft(dataset.id)
    assert repository.get_dataset_draft(dataset.id).id == first.id
    with sqlite3.connect(repository.path) as db:
        assert db.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM dataset_versions").fetchone()[0] == 1
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='business_state'"
        ).fetchone()[0] == 0


def test_dataset_catalog_rejects_changed_creation_time_and_stale_updates(tmp_path):
    repository = SQLiteRepository(tmp_path / "dataset-updates.db")
    service = DatasetService(repository)
    original = service.create_dataset("Original")
    current = original.model_copy(
        update={"name": "Current", "updated_at": original.updated_at + timedelta(seconds=2)}
    )
    repository.save_dataset(current)

    changed_creation = current.model_copy(
        update={"created_at": current.created_at - timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="created_at is immutable"):
        repository.save_dataset(changed_creation)

    stale = original.model_copy(update={"name": "Stale"})
    with pytest.raises(ValueError, match="stale Dataset"):
        repository.save_dataset(stale)
    assert repository.get_dataset(original.id) == current


def test_stale_draft_identity_cannot_delete_or_replace_current_data(tmp_path):
    repository = SQLiteRepository(tmp_path / "stale-draft.db")
    service = DatasetService(repository)
    dataset = service.create_dataset("Dataset")
    draft = service.create_draft(dataset.id)

    with pytest.raises(ValueError, match="expected Dataset draft"):
        repository.delete_dataset_draft(dataset.id, "stale-draft-id")
    assert repository.get_dataset_draft(dataset.id) == draft

    service.save_case(
        dataset.id,
        Case(name="Case", turns=(CaseTurn(input={"message": "hello"}),)),
    )
    published = service.publish_draft(dataset.id)
    with pytest.raises(ValueError, match="expected Dataset draft"):
        repository.replace_dataset_draft(draft.id, published)
    assert repository.get_published_dataset_version(dataset.id, 1) == published


def test_draft_save_preserves_identity_and_rejects_stale_content(tmp_path):
    repository = SQLiteRepository(tmp_path / "draft-updates.db")
    service = DatasetService(repository)
    dataset = service.create_dataset("Dataset")
    original = service.create_draft(dataset.id)
    current = DatasetVersion.model_validate(
        {
            **original.model_dump(mode="json"),
            "notes": "current",
            "updated_at": original.updated_at + timedelta(seconds=2),
            "content_sha256": "",
        }
    )
    repository.save_dataset_version(current)

    invalid_updates = (
        original.model_copy(update={"dataset_id": "other-dataset"}),
        current.model_copy(
            update={"created_at": current.created_at - timedelta(seconds=1)}
        ),
        original.model_copy(update={"notes": "stale"}),
        current.model_copy(
            update={
                "status": DatasetVersionStatus.PUBLISHED,
                "version": 1,
                "published_at": current.updated_at,
            }
        ),
    )
    for invalid in invalid_updates:
        with pytest.raises(ValueError):
            repository.save_dataset_version(invalid)
    assert repository.get_dataset_draft(dataset.id) == current


def test_replacement_rejects_changed_draft_without_partial_publication(tmp_path):
    repository = SQLiteRepository(tmp_path / "changed-draft.db")
    service = DatasetService(repository)
    dataset = service.create_dataset("Dataset")
    service.create_draft(dataset.id)
    original = service.save_case(
        dataset.id,
        Case(name="Case", turns=(CaseTurn(input={"message": "original"}),)),
    )
    published_at = original.updated_at + timedelta(seconds=1)
    candidate = DatasetVersion.model_validate(
        {
            **original.model_dump(mode="json"),
            "id": str(uuid4()),
            "version": 1,
            "status": DatasetVersionStatus.PUBLISHED,
            "updated_at": published_at,
            "published_at": published_at,
            "content_sha256": "",
        }
    )
    changed = original.model_copy(
        update={
            "notes": "changed after candidate was built",
            "updated_at": original.updated_at + timedelta(seconds=1),
            "content_sha256": "",
        }
    )
    changed = DatasetVersion.model_validate(changed.model_dump(mode="json"))
    repository.save_dataset_version(changed)

    with pytest.raises(ValueError, match="content does not match"):
        repository.replace_dataset_draft(original.id, candidate)
    assert repository.get_dataset_draft(dataset.id) == changed
    assert repository.get_published_dataset_version(dataset.id, 1) is None


def test_dataset_version_queries_are_explicit_and_deterministic(tmp_path):
    repository = SQLiteRepository(tmp_path / "version-queries.db")
    service = DatasetService(repository)
    dataset = service.create_dataset("Dataset")
    service.create_draft(dataset.id)
    service.save_case(
        dataset.id,
        Case(name="Case", turns=(CaseTurn(input={"message": "hello"}),)),
    )
    first = service.publish_draft(dataset.id)
    draft = service.create_draft(dataset.id, based_on_version=1)

    assert repository.get_published_dataset_version(dataset.id, 1) == first
    assert repository.get_published_dataset_version(dataset.id, 2) is None
    assert repository.get_latest_published_dataset_version(dataset.id) == first
    assert repository.get_dataset_draft(dataset.id) == draft
    assert repository.list_dataset_versions(dataset.id) == [draft, first]
    assert repository.list_dataset_versions(dataset.id, include_draft=False) == [first]


def test_published_payload_cannot_be_overwritten(tmp_path):
    repository = SQLiteRepository(tmp_path / "immutable.db")
    service = DatasetService(repository)
    dataset = service.create_dataset("Dataset")
    service.create_draft(dataset.id)
    service.save_case(dataset.id, Case(
        name="Case", turns=(CaseTurn(input={"message": "hello"}),)
    ))
    published = service.publish_draft(dataset.id)
    repository.save_dataset_version(published)
    changed = published.model_copy(update={"notes": "tampered"})
    with pytest.raises(ValueError, match="immutable"):
        repository.save_dataset_version(changed)
