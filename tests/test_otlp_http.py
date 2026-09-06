import json

import pytest

from agentgate.storage.sqlite import SQLiteRepository
from agentgate.integrations.observability import ingest_otlp_http_json
from agentgate.trace.normalizer import normalize_otlp_json


def attribute(key, value):
    field = "boolValue" if isinstance(value, bool) else "stringValue"
    return {"key": key, "value": {field: value}}


def complete_payload(*, include_owner=True, include_completion=True):
    resource_attributes = []
    if include_owner:
        resource_attributes = [
            attribute("agentgate.run.id", "run"),
            attribute("agentgate.case.id", "case"),
        ]
    span_attributes = [
        attribute("agentgate.operation.type", "routing"),
        attribute("selected_skill", "loan_approval"),
        attribute("agentgate.turn.id", "turn-1"),
        attribute("agentgate.turn.complete", True),
        attribute("agentgate.turn.input", json.dumps({"message": "hello"})),
        attribute("agentgate.turn.output", json.dumps({"message": "done"})),
        attribute("agentgate.turn.state", json.dumps({"status": "done"})),
    ]
    if include_completion:
        span_attributes.extend(
            [
                attribute("agentgate.trace.complete", True),
                attribute("agentgate.final.output", json.dumps({"message": "done"})),
                attribute("agentgate.final.state", json.dumps({"status": "done"})),
            ]
        )
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": resource_attributes},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "0" * 32,
                                "spanId": "1" * 16,
                                "name": "route",
                                "startTimeUnixNano": "1000000000",
                                "endTimeUnixNano": "2000000000",
                                "status": {"code": 1},
                                "attributes": span_attributes,
                            }
                        ]
                    }
                ],
            }
        ]
    }


def test_receiver_normalizes_and_persists_complete_otlp_json(tmp_path):
    repository = SQLiteRepository(tmp_path / "receiver.db")

    assert ingest_otlp_http_json(complete_payload(), repository) == 1

    trace = repository.get_trace("run", "case")
    assert trace.spans[0].operation_type == "routing"
    assert trace.spans[0].attributes["selected_skill"] == "loan_approval"
    assert trace.final_output == {"message": "done"}
    assert trace.turn_outcomes["turn-1"]["state"] == {"status": "done"}


def test_normalizer_rejects_missing_correlation_and_completion():
    with pytest.raises(ValueError, match="payload must be an object"):
        normalize_otlp_json([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="agentgate.run.id"):
        normalize_otlp_json(complete_payload(include_owner=False))
    with pytest.raises(ValueError, match="exactly one completion"):
        normalize_otlp_json(complete_payload(include_completion=False))


def test_normalizer_accepts_p1_owner_aliases():
    payload = complete_payload()
    resource_attributes = payload["resourceSpans"][0]["resource"]["attributes"]
    resource_attributes[0]["key"] = "agentgate.run_id"
    resource_attributes[1]["key"] = "agentgate.case_id"

    trace = normalize_otlp_json(payload)[0]

    assert trace.run_id == "run"
    assert trace.case_id == "case"
    assert "agentgate.run_id" not in trace.spans[0].attributes


def test_normalizer_rejects_conflicting_attribute_aliases():
    payload = complete_payload()
    payload["resourceSpans"][0]["resource"]["attributes"].append(
        attribute("agentgate.run_id", "other-run")
    )

    with pytest.raises(ValueError, match="conflicting Trace attribute aliases"):
        normalize_otlp_json(payload)


def test_normalizer_orders_spans_by_time_instead_of_payload_position():
    payload = complete_payload()
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    spans.append(
        {
            "traceId": "0" * 32,
            "spanId": "2" * 16,
            "name": "earlier",
            "startTimeUnixNano": "100000000",
            "endTimeUnixNano": "200000000",
            "attributes": [attribute("agentgate.operation.type", "agent")],
        }
    )

    trace = normalize_otlp_json(payload)[0]

    assert [span.name for span in trace.spans] == ["earlier", "route"]
    assert [span.sequence for span in trace.spans] == [0, 1]


def test_normalizer_allows_ownership_only_on_root_span():
    payload = complete_payload()
    resource_attributes = payload["resourceSpans"][0]["resource"]["attributes"]
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    spans[0]["attributes"].extend(resource_attributes)
    resource_attributes.clear()
    spans.append(
        {
            "traceId": "0" * 32,
            "spanId": "2" * 16,
            "parentSpanId": "1" * 16,
            "name": "agent-child",
            "startTimeUnixNano": "1100000000",
            "endTimeUnixNano": "1200000000",
            "attributes": [attribute("agentgate.operation.type", "agent")],
        }
    )

    trace = normalize_otlp_json(payload)[0]

    assert trace.run_id == "run"
    assert trace.case_id == "case"
    assert "agentgate.run.id" not in trace.spans[1].attributes
