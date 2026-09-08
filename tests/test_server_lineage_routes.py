from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from agentgate.server.app import create_app
from agentgate.demo.targets import get_demo_target_descriptor
from agentgate.domain import TargetDescriptor


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


def test_reverse_lineage_endpoints_return_related_runs(tmp_path) -> None:
    app = create_app(tmp_path / "reverse-lineage-routes.db")
    dependencies = app.state.dependencies
    baseline = dependencies.execute_demo_run("loan-agent-v1-risky")
    candidate = dependencies.execute_demo_run("loan-agent-v2-fixed")
    dataset = candidate.manifest.dataset
    case = dataset.cases[0]
    evaluator = candidate.manifest.evaluator_specs[0]
    requests = {
        "dataset": (
            f"/api/datasets/{dataset.dataset_id}/versions/{dataset.version}/lineage",
            {baseline.id, candidate.id},
        ),
        "case": (
            f"/api/datasets/{dataset.dataset_id}/versions/{dataset.version}"
            f"/cases/{case.id}/lineage",
            {baseline.id, candidate.id},
        ),
        "target": (
            "/api/targets/agentgate-demo/agent/loan-agent/versions/"
            "loan-agent-v2-fixed/lineage",
            {candidate.id},
        ),
        "skill": (
            "/api/skills/agentgate-demo/repayment_plan/versions/"
            "repayment-plan-v1/lineage",
            {baseline.id, candidate.id},
        ),
        "evaluator": (
            f"/api/evaluators/{evaluator.id}/versions/{evaluator.version}/lineage",
            {baseline.id, candidate.id},
        ),
    }

    with TestClient(app) as client:
        for _, (path, expected_run_ids) in requests.items():
            response = client.get(path)
            assert response.status_code == 200
            assert {
                node["external_id"]
                for node in response.json()["nodes"]
                if node["kind"] == "run"
            } == expected_run_ids


def test_reverse_lineage_routes_validate_requests_and_unknown_assets(tmp_path) -> None:
    with TestClient(create_app(tmp_path / "invalid-reverse-lineage.db")) as client:
        unknown = client.get("/api/datasets/missing/versions/1/lineage")
        invalid_version = client.get("/api/datasets/missing/versions/0/lineage")
        invalid_limit = client.get(
            "/api/datasets/loan-policy/versions/1/lineage?limit=0"
        )
        invalid_type = client.get(
            "/api/targets/source/workflow/target/versions/v1/lineage"
        )
        invalid_hash = client.get(
            "/api/skills/source/skill/versions/v1/lineage?content_sha256=bad"
        )

    assert unknown.status_code == 404
    assert invalid_version.status_code == 422
    assert invalid_limit.status_code == 422
    assert invalid_type.status_code == 422
    assert invalid_hash.status_code == 422


def test_target_lineage_route_requires_hash_when_version_is_ambiguous(tmp_path) -> None:
    app = create_app(tmp_path / "ambiguous-lineage-route.db")
    original = get_demo_target_descriptor("loan-agent-v2-fixed")
    mutated_payload = original.model_dump(
        mode="json", exclude={"content_sha256", "prompt_sha256"}
    )
    mutated_payload["prompt"] = "Mutated in place by the external platform."
    mutated = TargetDescriptor.model_validate(mutated_payload)
    app.state.dependencies.targets.register_descriptor(mutated)

    path = (
        "/api/targets/agentgate-demo/agent/loan-agent/versions/"
        "loan-agent-v2-fixed/lineage"
    )
    with TestClient(app) as client:
        ambiguous = client.get(path)
        selected = client.get(
            path, params={"content_sha256": original.content_sha256}
        )

    assert ambiguous.status_code == 409
    assert selected.status_code == 200
