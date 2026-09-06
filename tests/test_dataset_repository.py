import sqlite3

import pytest

from agentgate.case import DatasetService
from agentgate.domain import Case, CaseTurn
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


def test_published_payload_cannot_be_overwritten(tmp_path):
    repository = SQLiteRepository(tmp_path / "immutable.db")
    service = DatasetService(repository)
    dataset = service.create_dataset("Dataset")
    service.create_draft(dataset.id)
    service.save_case(dataset.id, Case(
        name="Case", turns=(CaseTurn(input={"message": "hello"}),)
    ))
    published = service.publish_draft(dataset.id)
    changed = published.model_copy(update={"notes": "tampered"})
    with pytest.raises(ValueError, match="immutable"):
        repository.save_dataset_version(changed)
