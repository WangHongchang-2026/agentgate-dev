import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.server.dependencies import ServerDependencies, build_dependencies
from agentgate.server.routes.telemetry import MAX_REQUEST_BYTES, router


def _attribute(key: str, value: str | bool) -> dict:
    field = "boolValue" if isinstance(value, bool) else "stringValue"
    return {"key": key, "value": {field: value}}


def _payload() -> dict:
    attributes = [
        _attribute("agentgate.operation.type", "turn"),
        _attribute("agentgate.turn.id", "turn"),
        _attribute("agentgate.turn.complete", True),
        _attribute("agentgate.turn.input", json.dumps({"message": "hello"})),
        _attribute("agentgate.turn.output", json.dumps({"message": "done"})),
        _attribute("agentgate.turn.state", json.dumps({})),
        _attribute("agentgate.trace.complete", True),
        _attribute("agentgate.final.output", json.dumps({"message": "done"})),
        _attribute("agentgate.final.state", json.dumps({})),
    ]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attribute("agentgate.run.id", "external-run"),
                        _attribute("agentgate.case.id", "external-case"),
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "a" * 32,
                                "spanId": "b" * 16,
                                "name": "agent.turn",
                                "startTimeUnixNano": "1000000000",
                                "endTimeUnixNano": "2000000000",
                                "attributes": attributes,
                            }
                        ]
                    }
                ],
            }
        ]
    }


def _client(dependencies: ServerDependencies) -> TestClient:
    app = FastAPI()
    app.state.dependencies = dependencies
    app.include_router(router)
    return TestClient(app)


def test_telemetry_route_accepts_and_persists_otlp_json(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "telemetry-routes.db")

    with _client(dependencies) as client:
        response = client.post("/v1/traces", json=_payload())

    assert response.status_code == 202
    assert response.json() == {"accepted_spans": 1}
    stored = dependencies.repository.get_trace("external-run", "external-case")
    assert stored is not None
    assert stored.trace_id == "a" * 32


def test_telemetry_route_rejects_unsupported_content_type(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "telemetry-content-type.db")

    with _client(dependencies) as client:
        response = client.post(
            "/v1/traces",
            content=b"{}",
            headers={"Content-Type": "application/x-protobuf"},
        )

    assert response.status_code == 415


def test_telemetry_route_rejects_malformed_json(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "telemetry-json.db")

    with _client(dependencies) as client:
        response = client.post(
            "/v1/traces",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422

    with _client(dependencies) as client:
        response = client.post("/v1/traces", json=[])

    assert response.status_code == 422
    assert response.json()["detail"] == "OTLP payload must be an object"


def test_telemetry_route_rejects_oversized_body_before_parsing(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "telemetry-size.db")

    with _client(dependencies) as client:
        response = client.post(
            "/v1/traces",
            content=b"x" * (MAX_REQUEST_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "OTLP request body exceeds the 4 MiB limit"
