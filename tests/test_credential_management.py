import pytest

from agentgate.application.credential_management import ApiKeyManagement
from agentgate.domain.credential import ApiKeyMetadata, ApiKeyScope
from agentgate.integrations.credentials.encryption import (
    ApiKeyEncryptionError,
    ApiKeyEncryptor,
)
from agentgate.storage.sqlite import SQLiteRepository


MASTER_KEY = bytes(range(32))


def management(tmp_path) -> tuple[ApiKeyManagement, SQLiteRepository]:
    repository = SQLiteRepository(tmp_path / "api-key-management.db")
    return ApiKeyManagement(repository, ApiKeyEncryptor(MASTER_KEY)), repository


def test_api_key_management_encrypts_creation_and_returns_only_metadata(
    tmp_path,
) -> None:
    service, repository = management(tmp_path)

    created = service.create_api_key(
        name="  Private judge key  ",
        provider_id="  company-llm  ",
        scope=ApiKeyScope.PRIVATE,
        plaintext="  sk-private-provider-value  ",
    )

    assert created.name == "Private judge key"
    assert created.provider_id == "company-llm"
    assert created.scope is ApiKeyScope.PRIVATE
    assert "plaintext" not in type(created).model_fields
    assert "sk-private-provider-value" not in created.model_dump_json()
    encrypted = repository.get_encrypted_api_key(created.id)
    assert encrypted is not None
    assert "sk-private-provider-value" not in encrypted
    assert service.get_api_key(created.id) == created
    assert service.list_api_keys() == [created]


def test_api_key_management_resolves_exact_plaintext_only_on_internal_call(
    tmp_path,
) -> None:
    service, _ = management(tmp_path)
    created = service.create_api_key(
        name="Shared agent key",
        provider_id="company-agent",
        scope=ApiKeyScope.SHARED,
        plaintext="  shared-provider-value  ",
    )

    assert service.resolve_api_key(created.id) == "  shared-provider-value  "


def test_api_key_management_deletes_metadata_and_encrypted_material(tmp_path) -> None:
    service, repository = management(tmp_path)
    created = service.create_api_key(
        name="Private agent key",
        provider_id="company-agent",
        scope=ApiKeyScope.PRIVATE,
        plaintext="private-provider-value",
    )

    service.delete_api_key(created.id)

    assert repository.get_api_key_metadata(created.id) is None
    assert repository.get_encrypted_api_key(created.id) is None


@pytest.mark.parametrize("operation", ("get", "resolve", "delete"))
def test_api_key_management_rejects_unknown_ids(tmp_path, operation: str) -> None:
    service, _ = management(tmp_path)

    with pytest.raises(LookupError, match="unknown API Key: missing"):
        getattr(service, f"{operation}_api_key")("missing")


def test_api_key_management_surfaces_only_sanitized_decryption_failure(
    tmp_path,
) -> None:
    service, repository = management(tmp_path)
    metadata = ApiKeyMetadata(
        id="corrupted",
        name="Corrupted key",
        provider_id="company-llm",
        scope=ApiKeyScope.PRIVATE,
    )
    repository.save_api_key(metadata, "v1.invalid-encrypted-material")

    with pytest.raises(ApiKeyEncryptionError) as raised:
        service.resolve_api_key(metadata.id)

    assert str(raised.value) == "encrypted API Key cannot be decrypted"
    assert "invalid-encrypted-material" not in str(raised.value)
