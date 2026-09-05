from agentgate.storage.sqlite import SQLiteRepository
from agentgate.trace.receivers.otlp_http import ingest_otlp_http_json


def test_receiver_normalizes_and_persists_otlp_json(tmp_path):
    repository = SQLiteRepository(tmp_path / "receiver.db")
    payload = {"resourceSpans": [{"resource": {"attributes": [
        {"key": "agentgate.run_id", "value": {"stringValue": "run"}},
        {"key": "agentgate.case_id", "value": {"stringValue": "case"}},
    ]}, "scopeSpans": [{"spans": [{
        "traceId": "0" * 32, "spanId": "1" * 16, "name": "route",
        "attributes": [
            {"key": "agentgate.operation_type", "value": {"stringValue": "routing"}},
            {"key": "selected_skill", "value": {"stringValue": "loan_approval"}},
        ],
    }]}]}]}
    assert ingest_otlp_http_json(payload, repository) == 1
    trace = repository.get_trace("run", "case")
    assert trace.spans[0].operation_type == "routing"
    assert trace.spans[0].attributes["selected_skill"] == "loan_approval"
