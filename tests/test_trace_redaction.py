from __future__ import annotations

import pytest

from agentgate.domain import FrozenJsonObject, SpanStatus, Trace, TraceSpan
from agentgate.trace.redaction import REDACTION_MARKER, redact_trace, redact_value


def trace_with_sensitive_data() -> Trace:
    return Trace(
        trace_id="a" * 32,
        run_id="run-1",
        case_id="case-1",
        spans=(
            TraceSpan(
                trace_id="a" * 32,
                span_id="b" * 16,
                name="notify alice@example.com",
                operation_type="tool",
                sequence=2,
                status=SpanStatus.OK,
                attributes={
                    "http.request.header.authorization": "Bearer top-secret",
                    "tool": {
                        "arguments": {
                            "customer-name": "Alice Example",
                            "region": "Singapore",
                        },
                        "result": "card 4111 1111 1111 1111",
                    },
                    "database_url": "https://user:password@example.com/data",
                },
                events=(
                    FrozenJsonObject(
                        {
                            "message": "request failed; api_key=top-secret",
                            "password": "top-secret",
                        }
                    ),
                ),
            ),
        ),
        turn_outcomes={
            "turn-1": {
                "output": {"email-address": "alice@example.com"},
                "state": {"safe": "visible"},
            }
        },
        final_output={
            "message": "Contact alice@example.com using token:top-secret",
            "connection": "redis://user:password@cache.example/0",
            "reference": "1234567890123",
        },
        final_state={
            "phone_number": "+65 6123 4567",
            "tenant_private_value": "customer-secret",
        },
    )


def test_redact_trace_protects_every_payload_location_and_preserves_structure() -> None:
    original = trace_with_sensitive_data()

    protected = redact_trace(
        original,
        additional_sensitive_keys={"tenant.private-value"},
    )

    assert protected is not original
    assert protected.trace_id == original.trace_id
    assert protected.run_id == original.run_id
    assert protected.case_id == original.case_id
    assert protected.spans[0].span_id == original.spans[0].span_id
    assert protected.spans[0].sequence == original.spans[0].sequence
    assert protected.spans[0].status == original.spans[0].status
    assert protected.spans[0].name == f"notify {REDACTION_MARKER}"
    assert (
        protected.spans[0].attributes["http.request.header.authorization"]
        == REDACTION_MARKER
    )
    assert protected.spans[0].attributes["tool"]["arguments"]["customer-name"] == (
        REDACTION_MARKER
    )
    assert protected.spans[0].attributes["tool"]["arguments"]["region"] == "Singapore"
    assert protected.spans[0].attributes["tool"]["result"] == (
        f"card {REDACTION_MARKER}"
    )
    assert protected.spans[0].attributes["database_url"] == (
        "https://[redacted]@example.com/data"
    )
    assert protected.spans[0].events[0]["message"] == (
        f"request failed; api_key={REDACTION_MARKER}"
    )
    assert protected.spans[0].events[0]["password"] == REDACTION_MARKER
    assert protected.turn_outcomes["turn-1"]["output"]["email-address"] == (
        REDACTION_MARKER
    )
    assert protected.turn_outcomes["turn-1"]["state"]["safe"] == "visible"
    assert protected.final_output["message"] == (
        f"Contact {REDACTION_MARKER} using token:{REDACTION_MARKER}"
    )
    assert protected.final_output["connection"] == (
        "redis://[redacted]@cache.example/0"
    )
    assert protected.final_output["reference"] == "1234567890123"
    assert protected.final_state["phone_number"] == REDACTION_MARKER
    assert protected.final_state["tenant_private_value"] == REDACTION_MARKER

    assert original.spans[0].name == "notify alice@example.com"
    assert original.final_state["phone_number"] == "+65 6123 4567"


def test_redact_trace_is_idempotent_and_redacts_private_key_blocks() -> None:
    original = trace_with_sensitive_data().model_copy(
        update={
            "final_output": FrozenJsonObject(
                {
                    "log": "before\n-----BEGIN PRIVATE KEY-----\nsecret\n"
                    "-----END PRIVATE KEY-----\nafter"
                }
            )
        }
    )

    protected = redact_trace(original)

    assert protected.final_output["log"] == f"before\n{REDACTION_MARKER}\nafter"
    assert redact_trace(protected) == protected


@pytest.mark.parametrize("key", ["", "   ", "---"])
def test_redact_trace_rejects_invalid_additional_sensitive_keys(key: str) -> None:
    with pytest.raises(ValueError, match="additional sensitive keys"):
        redact_trace(trace_with_sensitive_data(), additional_sensitive_keys={key})


def test_redact_value_protects_nested_json_without_mutating_input() -> None:
    original = {
        "profile": {
            "email": "alice@example.com",
            "region": "Singapore",
        },
        "messages": ["token=top-secret", "visible"],
        "tenant.private-value": "customer-secret",
    }

    protected = redact_value(
        original,
        additional_sensitive_keys={"tenant.private-value"},
    )

    assert isinstance(protected, FrozenJsonObject)
    assert protected["profile"]["email"] == REDACTION_MARKER
    assert protected["profile"]["region"] == "Singapore"
    assert protected["messages"] == (f"token={REDACTION_MARKER}", "visible")
    assert protected["tenant.private-value"] == REDACTION_MARKER
    assert original["profile"]["email"] == "alice@example.com"
    assert original["messages"][0] == "token=top-secret"


@pytest.mark.parametrize("value", [None, True, 7, 2.5, "visible"])
def test_redact_value_preserves_safe_json_scalars(value: object) -> None:
    assert redact_value(value) == value


def test_redact_value_is_deterministic_and_idempotent() -> None:
    original = {"nested": [{"password": "top-secret"}]}

    first = redact_value(original)

    assert redact_value(original) == first
    assert redact_value(first) == first


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        ({1: "value"}, TypeError, "keys must be strings"),
        ({"value": float("inf")}, ValueError, "numbers must be finite"),
        ({"value": object()}, TypeError, "not JSON-compatible"),
    ],
)
def test_redact_value_rejects_invalid_json(
    value: object,
    error: type[Exception],
    message: str,
) -> None:
    with pytest.raises(error, match=message):
        redact_value(value)


@pytest.mark.parametrize("key", ["", "   ", "---"])
def test_redact_value_rejects_invalid_additional_sensitive_keys(key: str) -> None:
    with pytest.raises(ValueError, match="additional sensitive keys"):
        redact_value({}, additional_sensitive_keys={key})
