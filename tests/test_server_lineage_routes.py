from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from agentgate.server.app import create_app


def test_get_run_lineage(tmp_path) -> None:
    app = create_app(tmp_path / "lineage-routes.db")
    dependencies = app.state.dependencies
    run = dependencies.execute_demo_run("loan-agent-v2-fixed")

    with TestClient(app) as client:
        response = client.get(f"/api/runs/{run.id}/lineage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["root_node_id"] == f"run:{run.id}"
    assert {node["kind"] for node in payload["nodes"]} == {
        "run",
        "dataset",
        "case",
        "agent",
        "skill",
        "evaluator",
    }


def test_get_run_lineage_returns_not_found_for_unknown_run(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "missing-lineage.db")) as client:
        response = client.get("/api/runs/missing/lineage")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown EvaluationRun: missing"


def test_get_run_lineage_returns_conflict_for_missing_descriptor(tmp_path) -> None:
    database_path = tmp_path / "descriptor-lineage.db"
    app = create_app(database_path)
    dependencies = app.state.dependencies
    run = dependencies.execute_demo_run("loan-agent-v2-fixed")
    with sqlite3.connect(database_path) as database:
        database.execute(
            "DELETE FROM target_descriptors WHERE content_sha256=?",
            (run.manifest.target.descriptor_sha256,),
        )

    with TestClient(app) as client:
        response = client.get(f"/api/runs/{run.id}/lineage")

    assert response.status_code == 409
    assert response.json()["detail"].startswith("unknown TargetDescriptor")
