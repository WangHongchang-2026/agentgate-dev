from fastapi.testclient import TestClient

from agentgate.server.application import create_app


def _launch(client: TestClient) -> tuple[dict, str]:
    run = client.post("/api/evaluations", json={
        "version": "loan-agent-v1-risky",
        "dataset_id": "loan-risk-policy",
        "dataset_version": 1,
    }).json()
    return run, run["snapshot"]["dataset"]["cases"][0]["id"]


def test_add_run_case_to_new_and_existing_regression_dataset(tmp_path):
    with TestClient(create_app(tmp_path / "regression-api.db")) as client:
        run, case_id = _launch(client)
        created = client.post(
            f"/api/runs/{run['id']}/cases/{case_id}/regression",
            json={
                "new_dataset_name": "Loan regressions",
                "new_dataset_description": "Known failures",
                "reason": "direct approval",
            },
        )

        assert created.status_code == 201
        payload = created.json()
        assert payload["dataset"]["purpose"] == "regression"
        assert payload["draft"]["cases"][0]["provenance"]["source_run_id"] == run["id"]
        assert payload["case"]["provenance"]["reason"] == "direct approval"
        regression_id = payload["dataset"]["id"]
        assert any(
            item["id"] == regression_id and item["purpose"] == "regression"
            for item in client.get("/api/datasets").json()
        )

        duplicate = client.post(
            f"/api/runs/{run['id']}/cases/{case_id}/regression",
            json={"regression_dataset_id": regression_id},
        )
        assert duplicate.status_code == 422
        assert "already exists" in duplicate.json()["detail"]


def test_regression_endpoint_maps_missing_resources_and_invalid_target(tmp_path):
    with TestClient(create_app(tmp_path / "regression-errors.db")) as client:
        run, case_id = _launch(client)
        standard = client.post("/api/datasets", json={"name": "Standard"}).json()

        assert client.post(
            f"/api/runs/missing/cases/{case_id}/regression",
            json={"new_dataset_name": "Regressions"},
        ).status_code == 404
        assert client.post(
            f"/api/runs/{run['id']}/cases/missing/regression",
            json={"new_dataset_name": "Regressions"},
        ).status_code == 404
        assert client.post(
            f"/api/runs/{run['id']}/cases/{case_id}/regression",
            json={"regression_dataset_id": standard["dataset"]["id"]},
        ).status_code == 422
        assert client.post(
            f"/api/runs/{run['id']}/cases/{case_id}/regression",
            json={},
        ).status_code == 422


def test_dataset_api_can_explicitly_create_regression_dataset(tmp_path):
    with TestClient(create_app(tmp_path / "regression-create.db")) as client:
        response = client.post("/api/datasets", json={
            "name": "Manual regressions",
            "purpose": "regression",
        })

    assert response.status_code == 201
    assert response.json()["dataset"]["purpose"] == "regression"
