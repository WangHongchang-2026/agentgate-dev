from datetime import UTC, datetime, timedelta
import sqlite3

import pytest

from agentgate.domain.credential import ApiKeyMetadata, ApiKeyScope
from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.storage.sqlite import SQLiteRepository


MASTER_KEY = bytes(range(32))
NOW = datetime(2026, 9, 9, tzinfo=UTC)


def metadata(
    api_key_id: str,
    *,
    created_at: datetime = NOW,
    scope: ApiKeyScope = ApiKeyScope.PRIVATE,
) -> ApiKeyMetadata:
    return ApiKeyMetadata(
        id=api_key_id,
        name=f"Key {api_key_id}",
        provider_id="company-llm",
        scope=scope,
        created_at=created_at,
        updated_at=created_at,
    )


def test_api_key_repository_persists_metadata_and_ciphertext_separately(
    tmp_path,
) -> None:
    path = tmp_path / "api-keys.db"
    repository = SQLiteRepository(path)
    item = metadata("private-key")
    plaintext = "sk-live-never-store-this"
    encrypted = ApiKeyEncryptor(MASTER_KEY).encrypt(plaintext)

    repository.save_api_key(item, encrypted)

    reopened = SQLiteRepository(path)
    assert reopened.get_api_key_metadata(item.id) == item
    assert reopened.get_encrypted_api_key(item.id) == encrypted
    assert reopened.get_api_key_metadata("missing") is None
    assert reopened.get_encrypted_api_key("missing") is None

    with sqlite3.connect(path) as db:
        stored = db.execute("SELECT * FROM api_keys WHERE id=?", (item.id,)).fetchone()
    assert stored is not None
    assert plaintext not in repr(stored)
    assert encrypted in stored


def test_api_key_repository_lists_oldest_first_then_id(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "api-key-order.db")
    encryptor = ApiKeyEncryptor(MASTER_KEY)
    items = (
        metadata("later", created_at=NOW + timedelta(seconds=1)),
        metadata("same-z"),
        metadata("same-a", scope=ApiKeyScope.SHARED),
    )
    for item in items:
        repository.save_api_key(item, encryptor.encrypt(f"secret-{item.id}"))

    assert [item.id for item in repository.list_api_key_metadata()] == [
        "same-a",
        "same-z",
        "later",
    ]


def test_api_key_repository_rejects_duplicate_without_overwriting(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "api-key-duplicate.db")
    original = metadata("duplicate")
    encrypted = ApiKeyEncryptor(MASTER_KEY).encrypt("original-secret")
    repository.save_api_key(original, encrypted)
    changed = original.model_copy(
        update={"name": "Changed", "updated_at": NOW + timedelta(seconds=1)}
    )

    with pytest.raises(ValueError, match="API Key already exists: duplicate"):
        repository.save_api_key(changed, "different-encrypted-value")

    assert repository.get_api_key_metadata(original.id) == original
    assert repository.get_encrypted_api_key(original.id) == encrypted


@pytest.mark.parametrize("encrypted", ("", "   ", None))
def test_api_key_repository_rejects_blank_encrypted_values(
    tmp_path,
    encrypted: object,
) -> None:
    repository = SQLiteRepository(tmp_path / "api-key-blank.db")

    with pytest.raises(ValueError, match="nonblank string"):
        repository.save_api_key(
            metadata("private-key"),
            encrypted,  # type: ignore[arg-type]
        )

    assert repository.list_api_key_metadata() == []


def test_api_key_repository_deletes_exact_existing_id(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "api-key-delete.db")
    encryptor = ApiKeyEncryptor(MASTER_KEY)
    first = metadata("first")
    second = metadata("second")
    repository.save_api_key(first, encryptor.encrypt("first-secret"))
    repository.save_api_key(second, encryptor.encrypt("second-secret"))

    repository.delete_api_key(first.id)

    assert repository.get_api_key_metadata(first.id) is None
    assert repository.get_encrypted_api_key(first.id) is None
    assert repository.get_api_key_metadata(second.id) == second
    with pytest.raises(ValueError, match="unknown API Key: first"):
        repository.delete_api_key(first.id)
