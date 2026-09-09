from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.server.dependencies import get_dependencies
from agentgate.server.routes.credentials import router


PLAINTEXT = "recognizable-unconfigured-api-key"


def test_api_key_routes_return_sanitized_503_when_unconfigured() -> None:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_dependencies] = lambda: SimpleNamespace(
        api_keys=None
    )

    with TestClient(application) as api:
        responses = (
            api.post(
                "/api/api-keys",
                json={
                    "name": "Unavailable key",
                    "provider_id": "company-llm",
                    "scope": "private",
                    "api_key": PLAINTEXT,
                },
            ),
            api.get("/api/api-keys"),
            api.get("/api/api-keys/missing"),
            api.delete("/api/api-keys/missing"),
        )

    for response in responses:
        assert response.status_code == 503
        assert response.json() == {
            "detail": "API Key management is unavailable"
        }
        assert PLAINTEXT not in response.text
