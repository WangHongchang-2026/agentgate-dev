"""Application workflows for secure API Key management."""

from __future__ import annotations

from agentgate.domain.credential import ApiKeyMetadata, ApiKeyScope
from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.storage.repository import AgentGateRepository


class ApiKeyManagement:
    """Coordinate secret-free metadata with encrypted API Key persistence."""

    def __init__(
        self,
        repository: AgentGateRepository,
        encryptor: ApiKeyEncryptor,
    ) -> None:
        self.repository = repository
        self.encryptor = encryptor

    def create_api_key(
        self,
        *,
        name: str,
        provider_id: str,
        scope: ApiKeyScope,
        plaintext: str,
    ) -> ApiKeyMetadata:
        """Encrypt and persist one API Key, returning safe metadata only."""

        metadata = ApiKeyMetadata(
            name=name.strip(),
            provider_id=provider_id.strip(),
            scope=scope,
        )
        encrypted = self.encryptor.encrypt(plaintext)
        self.repository.save_api_key(metadata, encrypted)
        return metadata

    def get_api_key(self, api_key_id: str) -> ApiKeyMetadata:
        metadata = self.repository.get_api_key_metadata(api_key_id)
        if metadata is None:
            raise LookupError(f"unknown API Key: {api_key_id}")
        return metadata

    def list_api_keys(self) -> list[ApiKeyMetadata]:
        return self.repository.list_api_key_metadata()

    def resolve_api_key(self, api_key_id: str) -> str:
        """Decrypt one stored API Key for an internal execution caller."""

        encrypted = self.repository.get_encrypted_api_key(api_key_id)
        if encrypted is None:
            raise LookupError(f"unknown API Key: {api_key_id}")
        return self.encryptor.decrypt(encrypted)

    def delete_api_key(self, api_key_id: str) -> None:
        self.get_api_key(api_key_id)
        try:
            self.repository.delete_api_key(api_key_id)
        except ValueError:
            raise LookupError(f"unknown API Key: {api_key_id}") from None


__all__ = ["ApiKeyManagement"]
