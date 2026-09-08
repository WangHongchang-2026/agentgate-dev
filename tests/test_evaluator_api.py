from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.evaluators import router


def _client(database_path) -> TestClient:
    app = FastAPI()
    app.state.dependencies = build_dependencies(database_path)
    app.include_router(router)
    return TestClient(app)


def _create_payload(
    *,
    name: str = "Custom output",
    metric: str = "custom_output",
    config: dict | None = None,
) -> dict:
    return {
        "name": name,
        "description": "Checks the final answer",
        "draft": {
            "kind": "rule",
            "dimension": "answer",
            "metric": metric,
            "severity": "standard",
            "implementation_id": "final_output",
            "implementation_version": "1",
            "config": config or {},
            "children": [],
            "combination": None,
        },
    }


def test_list_exposes_builtin_catalog_summaries(tmp_path) -> None:
    with _client(tmp_path / "evaluator-list.db") as client:
        response = client.get("/api/evaluators")

    assert response.status_code == 200
    items = response.json()
    assert len(items) == 7
    assert {item["source"] for item in items} == {"builtin"}
    assert all(item["enabled"] is True for item in items)
    assert all(item["latest_version"] == "1" for item in items)
    assert all(item["kind"] == "rule" for item in items)
    assert all(item["has_draft"] is False for item in items)
    assert all(item["created_at"] is not None for item in items)
    assert all(item["updated_at"] is not None for item in items)


def test_user_evaluator_api_lifecycle_preserves_exact_versions(tmp_path) -> None:
    with _client(tmp_path / "evaluator-lifecycle.db") as client:
        created_response = client.post(
            "/api/evaluators",
            json=_create_payload(),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        evaluator_id = created["evaluator"]["id"]
        assert created["evaluator"]["source"] == "user"
        assert created["evaluator"]["enabled"] is False
        assert created["draft"]["evaluator_id"] == evaluator_id

        assert evaluator_id not in {
            item["id"] for item in client.get("/api/evaluators").json()
        }
        all_items = client.get(
            "/api/evaluators", params={"include_disabled": True}
        ).json()
        summary = next(item for item in all_items if item["id"] == evaluator_id)
        assert summary["latest_version"] is None
        assert summary["metric"] == "custom_output"
        assert summary["has_draft"] is True

        enable_response = client.patch(
            f"/api/evaluators/{evaluator_id}",
            json={"enabled": True},
        )
        assert enable_response.status_code == 409

        first_response = client.post(
            f"/api/evaluators/{evaluator_id}/drafts/publish"
        )
        assert first_response.status_code == 200
        first = first_response.json()
        assert first["version"] == "1"

        enabled_response = client.patch(
            f"/api/evaluators/{evaluator_id}",
            json={"enabled": True},
        )
        assert enabled_response.status_code == 200
        assert enabled_response.json()["enabled"] is True

        detail = client.get(f"/api/evaluators/{evaluator_id}").json()
        assert detail["latest"] == first
        assert detail["draft"] is None

        cloned_response = client.post(
            f"/api/evaluators/{evaluator_id}/drafts",
            json={"based_on_version": "1"},
        )
        assert cloned_response.status_code == 201
        assert cloned_response.json()["based_on_version"] == "1"

        replacement = _create_payload(metric="custom_output_v2")["draft"]
        replacement["severity"] = "blocking"
        replaced_response = client.put(
            f"/api/evaluators/{evaluator_id}/drafts/current",
            json=replacement,
        )
        assert replaced_response.status_code == 200
        assert replaced_response.json()["metric"] == "custom_output_v2"

        second_response = client.post(
            f"/api/evaluators/{evaluator_id}/drafts/publish"
        )
        assert second_response.status_code == 200
        second = second_response.json()
        assert second["version"] == "2"

        versions = client.get(
            f"/api/evaluators/{evaluator_id}/versions"
        ).json()
        assert [item["version"] for item in versions] == ["2", "1"]
        exact_first = client.get(
            f"/api/evaluators/{evaluator_id}/versions/1"
        ).json()
        assert exact_first == first
        assert exact_first["metric"] == "custom_output"

        delete_response = client.delete(f"/api/evaluators/{evaluator_id}")
        assert delete_response.status_code == 409


def test_unpublished_evaluator_can_be_deleted_with_its_draft(tmp_path) -> None:
    with _client(tmp_path / "evaluator-delete.db") as client:
        created = client.post(
            "/api/evaluators",
            json=_create_payload(name="Disposable"),
        ).json()
        evaluator_id = created["evaluator"]["id"]

        response = client.delete(f"/api/evaluators/{evaluator_id}")

        assert response.status_code == 204
        assert client.get(f"/api/evaluators/{evaluator_id}").status_code == 404


def test_builtin_mutation_and_unknown_resources_have_stable_statuses(tmp_path) -> None:
    with _client(tmp_path / "evaluator-errors.db") as client:
        assert (
            client.patch(
                "/api/evaluators/final-output",
                json={"name": "Changed"},
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/evaluators/final-output/drafts",
                json={"based_on_version": "1"},
            ).status_code
            == 409
        )
        assert (
            client.get("/api/evaluators/final-output/versions/2").status_code
            == 404
        )
        assert client.get("/api/evaluators/missing").status_code == 404


def test_invalid_requests_and_publication_return_unprocessable(tmp_path) -> None:
    with _client(tmp_path / "evaluator-invalid.db") as client:
        payload = _create_payload(config={"unsupported": True})
        payload["source"] = "builtin"
        assert client.post("/api/evaluators", json=payload).status_code == 422

        payload.pop("source")
        created = client.post("/api/evaluators", json=payload).json()
        evaluator_id = created["evaluator"]["id"]
        assert (
            client.patch(f"/api/evaluators/{evaluator_id}", json={}).status_code
            == 422
        )
        assert (
            client.patch(
                f"/api/evaluators/{evaluator_id}",
                json={"name": None},
            ).status_code
            == 422
        )

        publish_response = client.post(
            f"/api/evaluators/{evaluator_id}/drafts/publish"
        )
        assert publish_response.status_code == 422
        assert (
            client.get(
                f"/api/evaluators/{evaluator_id}/drafts/current"
            ).status_code
            == 200
        )
