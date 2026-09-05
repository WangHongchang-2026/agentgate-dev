from fastapi.testclient import TestClient

from agentgate.server.application import create_app


def test_api_evaluation_and_persisted_trace(tmp_path):
    with TestClient(create_app(tmp_path / "api.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v1-risky",
            "dataset_id": "loan-risk-policy",
            "dataset_version": 1,
        })
        assert response.status_code == 201
        run_id = response.json()["id"]
        report = client.get(f"/api/runs/{run_id}").json()
        assert report["gate"]["outcome"] == "fail"
        trace = client.get(f"/api/runs/{run_id}/traces/high-risk-approval")
        assert trace.status_code == 200
        assert any(span["name"] == "approve_loan" for span in trace.json()["spans"])


def test_api_launch_requires_an_explicit_dataset_version(tmp_path):
    with TestClient(create_app(tmp_path / "explicit-version.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy",
        })
        assert response.status_code == 422


def test_otlp_http_uses_post_and_health_is_separate(tmp_path):
    payload = {"resourceSpans": [{"resource": {"attributes": [
        {"key": "agentgate.run_id", "value": {"stringValue": "external-run"}},
        {"key": "agentgate.case_id", "value": {"stringValue": "external-case"}},
    ]}, "scopeSpans": [{"spans": [{"traceId": "a" * 32, "spanId": "d" * 16, "name": "tool.call",
                                      "attributes": [{"key": "agentgate.operation_type", "value": {"stringValue": "tool"}}]}]}]}]}
    with TestClient(create_app(tmp_path / "otlp.db")) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/v1/traces").status_code == 405
        response = client.post("/v1/traces", json=payload)
        assert response.status_code == 202
        assert response.json() == {"accepted_spans": 1}
        stored = client.app.state.repository.get_trace("external-run", "external-case")
        assert stored is not None and stored.spans[0].name == "tool.call"
