import base64

import pytest

from agentgate.domain.credential import ApiKeyScope
from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.integrations.credentials.environment import (
    API_KEY_ENCRYPTION_KEY_ENV,
)
from agentgate.server.dependencies import build_dependencies


MASTER_KEY = bytes(range(32))


def test_dependencies_accept_an_explicit_api_key_encryptor(tmp_path) -> None:
    dependencies = build_dependencies(
        tmp_path / "injected-api-keys.db",
        api_key_encryptor=ApiKeyEncryptor(MASTER_KEY),
    )
    try:
        assert dependencies.api_keys is not None
        created = dependencies.api_keys.create_api_key(
            name="Private judge key",
            provider_id="company-llm",
            scope=ApiKeyScope.PRIVATE,
            plaintext="provider-key-value",
        )
        assert dependencies.api_keys.resolve_api_key(created.id) == (
            "provider-key-value"
        )
    finally:
        dependencies.close()


def test_dependencies_load_api_key_encryptor_from_environment(
    tmp_path,
    monkeypatch,
) -> None:
    encoded = base64.urlsafe_b64encode(MASTER_KEY).decode("ascii")
    monkeypatch.setenv(API_KEY_ENCRYPTION_KEY_ENV, encoded)

    dependencies = build_dependencies(tmp_path / "environment-api-keys.db")
    try:
        assert dependencies.api_keys is not None
    finally:
        dependencies.close()


def test_dependencies_leave_only_api_key_management_unavailable_when_missing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENCRYPTION_KEY_ENV, raising=False)

    dependencies = build_dependencies(tmp_path / "missing-api-keys.db")
    try:
        assert dependencies.api_keys is None
        assert dependencies.datasets is not None
        assert dependencies.runs is not None
        assert dependencies.results is not None
    finally:
        dependencies.close()


def test_dependencies_fail_closed_for_malformed_api_key_configuration(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENCRYPTION_KEY_ENV, "not+urlsafe/secret-value")

    with pytest.raises(ValueError) as raised:
        build_dependencies(tmp_path / "malformed-api-keys.db")

    message = str(raised.value)
    assert API_KEY_ENCRYPTION_KEY_ENV in message
    assert "not+urlsafe/secret-value" not in message
