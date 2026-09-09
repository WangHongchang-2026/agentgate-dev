from fastapi.testclient import TestClient

from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.integrations.credentials.environment import (
    API_KEY_ENCRYPTION_KEY_ENV,
)
from agentgate.server.app import create_app


MASTER_KEY = bytes(range(32))
PLAINTEXT = "recognizable-real-app-api-key"


def test_application_factory_registers_configured_api_key_routes(tmp_path) -> None:
    application = create_app(
        tmp_path / "configured-api-keys.db",
        api_key_encryptor=ApiKeyEncryptor(MASTER_KEY),
    )

    assert set(application.openapi()["paths"]["/api/api-keys"]) == {
        "get",
        "post",
    }
    assert set(application.openapi()["paths"]["/api/api-keys/{api_key_id}"]) == {
        "delete",
        "get",
    }

    with TestClient(application) as api:
        created = api.post(
            "/api/api-keys",
            json={
                "name": "Real application key",
                "provider_id": "company-llm",
                "scope": "private",
                "api_key": PLAINTEXT,
            },
        )
        listed = api.get("/api/api-keys")
        deleted = api.delete(f"/api/api-keys/{created.json()['id']}")

    assert created.status_code == 201
    assert listed.json() == [created.json()]
    assert deleted.status_code == 204
    assert PLAINTEXT not in created.text + listed.text


def test_application_factory_keeps_api_key_routes_safely_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENCRYPTION_KEY_ENV, raising=False)
    application = create_app(tmp_path / "unconfigured-api-keys.db")

    with TestClient(application) as api:
        response = api.get("/api/api-keys")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "API Key management is unavailable"
    }
