import json

from fastapi.testclient import TestClient

from agentgate.server.app import create_app


def otlp_attribute(key, value):
    field = "boolValue" if isinstance(value, bool) else "stringValue"
    return {"key": key, "value": {field: value}}


def completed_otlp_payload():
    span_attributes = [
        otlp_attribute("agentgate.operation.type", "tool"),
        otlp_attribute("agentgate.turn.id", "turn"),
        otlp_attribute("agentgate.turn.complete", True),
        otlp_attribute("agentgate.turn.input", json.dumps({"message": "hello"})),
        otlp_attribute("agentgate.turn.output", json.dumps({"message": "done"})),
        otlp_attribute("agentgate.turn.state", json.dumps({})),
        otlp_attribute("agentgate.trace.complete", True),
        otlp_attribute("agentgate.final.output", json.dumps({"message": "done"})),
        otlp_attribute("agentgate.final.state", json.dumps({})),
    ]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        otlp_attribute("agentgate.run.id", "external-run"),
                        otlp_attribute("agentgate.case.id", "external-case"),
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "a" * 32,
                                "spanId": "d" * 16,
                                "name": "tool.call",
                                "startTimeUnixNano": "1000000000",
                                "endTimeUnixNano": "2000000000",
                                "attributes": span_attributes,
                            }
                        ]
                    }
                ],
            }
        ]
    }


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
        assert report["release_gate"]["outcome"] == "fail"
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
    payload = completed_otlp_payload()
    with TestClient(create_app(tmp_path / "otlp.db")) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/v1/traces").status_code == 405
        response = client.post("/v1/traces", json=payload)
        assert response.status_code == 202
        assert response.json() == {"accepted_spans": 1}
        stored = client.app.state.dependencies.repository.get_trace(
            "external-run", "external-case"
        )
        assert stored is not None and stored.spans[0].name == "tool.call"
