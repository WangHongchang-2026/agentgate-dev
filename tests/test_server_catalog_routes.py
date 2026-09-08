from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.catalogs import router


def _client(database_path) -> TestClient:
    app = FastAPI()
    app.state.dependencies = build_dependencies(database_path)
    app.include_router(router)
    return TestClient(app)


def test_target_version_catalog_preserves_demo_contract(tmp_path) -> None:
    with _client(tmp_path / "versions.db") as client:
        response = client.get("/api/versions")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "loan-agent-v1-risky", "label": "Risky version"},
        {"id": "loan-agent-v2-fixed", "label": "Fixed version"},
    ]
