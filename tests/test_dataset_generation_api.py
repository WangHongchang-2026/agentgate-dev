import json

import httpx
from fastapi.testclient import TestClient

from agentgate.case.generation.fake import FakeGenerationModel
from agentgate.server.application import create_app
from agentgate.integrations.model_providers import (
    OpenAICompatibleGenerationModel,
    RuntimeCredentialStore,
)


def _model_response():
    return json.dumps({"cases": [{
        "slot_index": 0,
        "name": "查询订单",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "查询订单 ORD-2026-100"},
            "expected_skill": "order_query",
            "required_tool_calls": [{
                "tool": "get_order",
                "arguments": {"order_id": "ORD-2026-100"},
            }],
        }],
    }]})


def _generation_payload(draft):
    return {
        "draft_id": draft["id"],
        "draft_content_sha256": draft["content_sha256"],
        "target_ref": {
            "platform_id": "fake",
            "target_type": "agent",
            "external_target_id": "customer-service-agent",
            "external_version_id": "2.1.0",
        },
        "count": 1,
        "turn_mode": "single",
        "category_counts": {"positive": 1, "negative": 0, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 0, "hard": 0},
        "model_profile_id": "dataset-generator-default",
    }


def test_target_and_model_selection_endpoints_do_not_expose_secrets(tmp_path):
    with TestClient(create_app(tmp_path / "api.db", FakeGenerationModel(_model_response()))) as client:
        targets = client.get("/api/targets").json()
        assert {item["target_type"] for item in targets} == {"agent", "skill"}
        versions = client.get("/api/targets/fake/agent/customer-service-agent/versions")
        assert versions.status_code == 200
        serialized = json.dumps(versions.json()).lower()
        assert "credential" not in serialized
        assert "base_url" not in serialized
        profiles = client.get("/api/dataset-generation/model-profiles").json()
        assert profiles == [{
            "id": "dataset-generator-default",
            "display_name": "阿里百炼 Qwen3.7 Plus",
            "provider": "openai-compatible",
            "model": "qwen3.7-plus",
            "available": True,
        }]


def test_model_credential_can_be_validated_and_kept_only_in_runtime_memory(tmp_path):
    secret = "secret-api-key-value"
    captured = {}

    def handler(request: httpx.Request):
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, headers={"x-request-id": "credential-check-1"}, json={})

    transport = httpx.MockTransport(handler)
    store = RuntimeCredentialStore(fallback=lambda _: None)
    model = OpenAICompatibleGenerationModel(
        credential_lookup=store.get,
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
    )
    with TestClient(create_app(
        tmp_path / "credential.db",
        model,
        generation_credential_store=store,
    )) as client:
        before = client.get("/api/dataset-generation/model-profiles").json()
        assert before[0]["available"] is False

        configured = client.put(
            "/api/dataset-generation/model-profiles/dataset-generator-default/credential",
            json={"api_key": secret},
        )
        assert configured.status_code == 200, configured.text
        assert configured.json() == {
            "profile_id": "dataset-generator-default",
            "available": True,
            "storage": "process_memory",
            "validation_request_id": "credential-check-1",
        }
        assert secret not in configured.text
        assert captured["authorization"] == f"Bearer {secret}"
        assert client.get("/api/dataset-generation/model-profiles").json()[0]["available"] is True

        deleted = client.delete(
            "/api/dataset-generation/model-profiles/dataset-generator-default/credential"
        )
        assert deleted.status_code == 200
        assert deleted.json()["available"] is False
        assert secret not in deleted.text


def test_rejected_model_credential_is_not_stored_or_echoed(tmp_path):
    secret = "rejected-secret-api-key"
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="upstream-secret"))
    store = RuntimeCredentialStore(fallback=lambda _: None)
    model = OpenAICompatibleGenerationModel(
        credential_lookup=store.get,
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
    )
    with TestClient(create_app(
        tmp_path / "rejected-credential.db",
        model,
        generation_credential_store=store,
    )) as client:
        response = client.put(
            "/api/dataset-generation/model-profiles/dataset-generator-default/credential",
            json={"api_key": secret},
        )

        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "provider_authentication_failed"
        assert secret not in response.text
        assert "upstream-secret" not in response.text
        assert store.get("DASHSCOPE_API_KEY") is None


def test_generate_validate_and_accept_candidates_over_http(tmp_path):
    model = FakeGenerationModel(_model_response())
    with TestClient(create_app(tmp_path / "flow.db", model)) as client:
        created = client.post("/api/datasets", json={"name": "Generated"})
        assert created.status_code == 201
        dataset_id = created.json()["dataset"]["id"]
        draft = created.json()["draft"]
        payload = _generation_payload(draft)
        generated = client.post(
            f"/api/datasets/{dataset_id}/drafts/generate-candidates", json=payload
        )
        assert generated.status_code == 200, generated.text
        result = generated.json()
        assert result["valid_count"] == 1
        assert result["model_profile_id"] == "dataset-generator-default"
        candidate = result["candidates"][0]
        assert candidate["review_status"] == "pending"
        turn = candidate["case"]["turns"][0]
        assert turn["expected_skill"] == "order_query"
        assert turn["required_tools"] == ["get_order"]
        assert [item["kind"] for item in turn["expectations"]] == [
            "tool_argument", "output",
        ]
        assert turn["expectations"][0]["path"] == "order_id"
        assert turn["expectations"][1]["condition"]["kind"] == "matches_json_schema"

        validation = client.post(
            f"/api/datasets/{dataset_id}/drafts/generated-candidates/validate",
            json={
                "draft_id": draft["id"],
                "draft_content_sha256": draft["content_sha256"],
                "target_ref": result["target_ref"],
                "target_descriptor_sha256": result["target_descriptor_sha256"],
                "recipe_version": result["recipe_version"],
                "acceptance_token": result["acceptance_token"],
                "candidate_id": candidate["candidate_id"],
                "slot_index": candidate["slot_index"],
                "case": candidate["case"],
            },
        )
        assert validation.status_code == 200
        assert validation.json()["issues"] == []

        accept_body = {
            "draft_id": draft["id"],
            "draft_content_sha256": draft["content_sha256"],
            "target_ref": result["target_ref"],
            "target_descriptor_sha256": result["target_descriptor_sha256"],
            "recipe_version": result["recipe_version"],
            "acceptance_token": result["acceptance_token"],
            "candidates": [{
                "slot_index": candidate["slot_index"],
                "case": candidate["case"],
            }],
        }
        accepted = client.post(
            f"/api/datasets/{dataset_id}/drafts/cases/batch",
            headers={"Idempotency-Key": "accept-http-1"},
            json=accept_body,
        )
        assert accepted.status_code == 200, accepted.text
        receipt = accepted.json()
        assert receipt["inserted_case_ids"] == [candidate["case"]["id"]]
        replay = client.post(
            f"/api/datasets/{dataset_id}/drafts/cases/batch",
            headers={"Idempotency-Key": "accept-http-1"},
            json=accept_body,
        )
        assert replay.json() == receipt
        current = client.get(f"/api/datasets/{dataset_id}/drafts/current").json()
        assert len(current["cases"]) == 1
        assert current["cases"][0]["generation_provenance"]["source_type"] == "llm_generation"
        assert current["cases"][0]["generation_provenance"]["requested_model"] == "qwen3.7-plus"
        published = client.post(f"/api/datasets/{dataset_id}/drafts/publish")
        assert published.status_code == 200, published.text
        assert published.json()["version"] == 1
        assert published.json()["cases"][0]["id"] == candidate["case"]["id"]


def test_skill_target_can_generate_and_accept_a_candidate(tmp_path):
    model = FakeGenerationModel(_model_response())
    with TestClient(create_app(tmp_path / "skill-flow.db", model)) as client:
        created = client.post("/api/datasets", json={"name": "Skill Generated"}).json()
        dataset_id = created["dataset"]["id"]
        payload = _generation_payload(created["draft"])
        payload["target_ref"] = {
            "platform_id": "fake",
            "target_type": "skill",
            "external_target_id": "order-query",
            "external_version_id": "deployment-20260903",
        }
        generated = client.post(
            f"/api/datasets/{dataset_id}/drafts/generate-candidates", json=payload
        )
        assert generated.status_code == 200, generated.text
        result = generated.json()
        assert result["valid_count"] == 1
        candidate = result["candidates"][0]
        accepted = client.post(
            f"/api/datasets/{dataset_id}/drafts/cases/batch",
            headers={"Idempotency-Key": "accept-skill-1"},
            json={
                "draft_id": result["draft_id"],
                "draft_content_sha256": result["draft_content_sha256"],
                "target_ref": result["target_ref"],
                "target_descriptor_sha256": result["target_descriptor_sha256"],
                "recipe_version": result["recipe_version"],
                "acceptance_token": result["acceptance_token"],
                "candidates": [{
                    "slot_index": candidate["slot_index"],
                    "case": candidate["case"],
                }],
            },
        )
        assert accepted.status_code == 200, accepted.text
        current = client.get(f"/api/datasets/{dataset_id}/drafts/current").json()
        provenance = current["cases"][0]["generation_provenance"]
        assert provenance["target_ref"]["target_type"] == "skill"
        assert provenance["target_ref"]["external_version_id"] == "deployment-20260903"


def test_acceptance_token_survives_application_restart(tmp_path):
    database = tmp_path / "restart-flow.db"
    with TestClient(create_app(database, FakeGenerationModel(_model_response()))) as client:
        created = client.post("/api/datasets", json={"name": "Restart Generated"}).json()
        dataset_id = created["dataset"]["id"]
        generated = client.post(
            f"/api/datasets/{dataset_id}/drafts/generate-candidates",
            json=_generation_payload(created["draft"]),
        ).json()

    candidate = generated["candidates"][0]
    with TestClient(create_app(database, FakeGenerationModel(_model_response()))) as restarted:
        accepted = restarted.post(
            f"/api/datasets/{dataset_id}/drafts/cases/batch",
            headers={"Idempotency-Key": "accept-after-restart"},
            json={
                "draft_id": generated["draft_id"],
                "draft_content_sha256": generated["draft_content_sha256"],
                "target_ref": generated["target_ref"],
                "target_descriptor_sha256": generated["target_descriptor_sha256"],
                "recipe_version": generated["recipe_version"],
                "acceptance_token": generated["acceptance_token"],
                "candidates": [{
                    "slot_index": candidate["slot_index"],
                    "case": candidate["case"],
                }],
            },
        )

        assert accepted.status_code == 200, accepted.text
        current = restarted.get(f"/api/datasets/{dataset_id}/drafts/current").json()
        assert [case["name"] for case in current["cases"]] == ["查询订单"]


def test_generate_returns_structured_error_when_model_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with TestClient(create_app(tmp_path / "missing-key.db")) as client:
        created = client.post("/api/datasets", json={"name": "Generated"}).json()
        dataset_id = created["dataset"]["id"]
        response = client.post(
            f"/api/datasets/{dataset_id}/drafts/generate-candidates",
            json=_generation_payload(created["draft"]),
        )
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "provider_credential_unavailable"
