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


def test_evaluator_catalog_exposes_execution_metadata_in_english(tmp_path) -> None:
    with _client(tmp_path / "evaluators.db") as client:
        response = client.get("/api/evaluators")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 7
    assert {item["id"] for item in items} == {
        "skill-routing",
        "required-tool",
        "forbidden-tool",
        "tool-arguments",
        "final-state",
        "final-output",
        "policy-compliance",
    }
    assert {item["kind"] for item in items} == {"rule"}
    assert all(item["name"].isascii() for item in items)
    assert set(items[0]) == {
        "id",
        "name",
        "kind",
        "version",
        "dimension",
        "metric",
        "severity",
        "implementation_id",
        "implementation_version",
        "config",
    }
