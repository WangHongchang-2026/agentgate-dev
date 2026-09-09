from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.application.credential_management import ApiKeyManagement
from agentgate.integrations.credentials.encryption import ApiKeyEncryptor
from agentgate.server.dependencies import get_dependencies
from agentgate.server.routes.credentials import router
from agentgate.storage.sqlite import SQLiteRepository


MASTER_KEY = bytes(range(32))
PLAINTEXT = "recognizable-provider-api-key"


def client(tmp_path) -> tuple[TestClient, SQLiteRepository]:
    repository = SQLiteRepository(tmp_path / "api-key-routes.db")
    management = ApiKeyManagement(repository, ApiKeyEncryptor(MASTER_KEY))
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_dependencies] = lambda: SimpleNamespace(
        api_keys=management
    )
    return TestClient(application), repository


def creation_payload() -> dict[str, str]:
    return {
        "name": "Private judge key",
        "provider_id": "company-llm",
        "scope": "private",
        "api_key": PLAINTEXT,
    }


def test_api_key_routes_create_list_and_get_only_safe_metadata(tmp_path) -> None:
    api, repository = client(tmp_path)

    with api:
        created = api.post("/api/api-keys", json=creation_payload())
        listed = api.get("/api/api-keys")
        detail = api.get(f"/api/api-keys/{created.json()['id']}")

    assert created.status_code == 201
    assert listed.status_code == 200
    assert detail.status_code == 200
    assert created.json() == detail.json() == listed.json()[0]
    assert set(created.json()) == {
        "id",
        "name",
        "provider_id",
        "scope",
        "created_at",
        "updated_at",
    }
    assert PLAINTEXT not in created.text + listed.text + detail.text
    encrypted = repository.get_encrypted_api_key(created.json()["id"])
    assert encrypted is not None
    assert PLAINTEXT not in encrypted


def test_api_key_routes_delete_and_reject_unknown_ids(tmp_path) -> None:
    api, _ = client(tmp_path)

    with api:
        created = api.post("/api/api-keys", json=creation_payload())
        deleted = api.delete(f"/api/api-keys/{created.json()['id']}")
        missing_detail = api.get(f"/api/api-keys/{created.json()['id']}")
        missing_delete = api.delete("/api/api-keys/missing")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert missing_detail.status_code == 404
    assert missing_delete.status_code == 404
    assert missing_detail.json()["detail"].startswith("unknown API Key:")
    assert missing_delete.json()["detail"] == "unknown API Key: missing"


def test_api_key_route_validation_never_echoes_submitted_key(tmp_path) -> None:
    api, repository = client(tmp_path)
    invalid_payloads = (
        {**creation_payload(), "name": "   "},
        {**creation_payload(), "api_key": "   "},
        {**creation_payload(), "scope": "unknown"},
        {**creation_payload(), "unexpected": "value"},
    )

    with api:
        responses = [
            api.post("/api/api-keys", json=payload)
            for payload in invalid_payloads
        ]

    assert all(response.status_code == 422 for response in responses)
    assert all(PLAINTEXT not in response.text for response in responses)
    assert repository.list_api_key_metadata() == []


def test_api_key_openapi_marks_secret_write_only(tmp_path) -> None:
    api, _ = client(tmp_path)

    schema = api.app.openapi()["components"]["schemas"]["CreateApiKeyRequest"]

    assert schema["additionalProperties"] is False
    assert schema["properties"]["api_key"]["format"] == "password"
    assert schema["properties"]["api_key"]["writeOnly"] is True
