from fastapi.testclient import TestClient

from agentgate.server.application import create_app


def launch(client):
    response = client.post("/api/evaluations", json={
        "version": "loan-agent-v1-risky",
        "dataset_id": "loan-risk-policy",
        "dataset_version": 1,
    })
    assert response.status_code == 201
    return response.json()


def test_single_case_rerun_api_creates_child_and_returns_comparison(tmp_path):
    with TestClient(create_app(tmp_path / "rerun-api.db")) as client:
        original = launch(client)
        case_id = original["snapshot"]["dataset"]["cases"][0]["id"]

        response = client.post(
            f"/api/runs/{original['id']}/cases/{case_id}/rerun",
            json={"target_version": "loan-agent-v2-fixed"},
        )

        assert response.status_code == 201
        rerun = response.json()
        assert rerun["snapshot"]["selected_case_ids"] == [case_id]
        comparison = client.get(f"/api/runs/{rerun['id']}/comparison")
        assert comparison.status_code == 200
        assert comparison.json()["parent_run_id"] == original["id"]
        assert comparison.json()["overall"] == "improved"


def test_single_case_rerun_api_maps_domain_errors(tmp_path):
    with TestClient(create_app(tmp_path / "rerun-errors.db")) as client:
        original = launch(client)
        case_id = original["snapshot"]["dataset"]["cases"][0]["id"]

        assert client.post(
            f"/api/runs/missing/cases/{case_id}/rerun", json={}
        ).status_code == 404
        assert client.post(
            f"/api/runs/{original['id']}/cases/missing/rerun", json={}
        ).status_code == 404
        assert client.post(
            f"/api/runs/{original['id']}/cases/{case_id}/rerun",
            json={"target_version": "missing"},
        ).status_code == 422
        assert client.get(f"/api/runs/{original['id']}/comparison").status_code == 422


def test_versions_mark_exactly_one_latest_target(tmp_path):
    with TestClient(create_app(tmp_path / "versions.db")) as client:
        response = client.get("/api/versions")
    assert response.status_code == 200
    versions = response.json()
    assert sum(item["is_latest"] for item in versions) == 1
    assert next(item["id"] for item in versions if item["is_latest"]) == (
        "loan-agent-v2-fixed"
    )
