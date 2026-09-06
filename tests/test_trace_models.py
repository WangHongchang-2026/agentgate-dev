from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agentgate.domain import SpanStatus, Trace, TraceSpan


TRACE_ID = "a" * 32
OTHER_TRACE_ID = "b" * 32


def span(span_id: str = "1" * 16, sequence: int = 0, **changes) -> TraceSpan:
    values = {
        "trace_id": TRACE_ID,
        "span_id": span_id,
        "name": "invoke tool",
        "operation_type": "tool",
        "sequence": sequence,
    }
    values.update(changes)
    return TraceSpan(**values)


def test_span_uses_otel_ids_and_normalizes_timestamps():
    offset = timezone(timedelta(hours=8))
    started = datetime(2026, 9, 5, 8, tzinfo=offset)
    value = span(
        parent_span_id="2" * 16,
        started_at=started,
        ended_at=started + timedelta(seconds=1),
        status=SpanStatus.OK,
        attributes={"arguments": {"amount": 80000}},
        events=({"name": "completed"},),
    )

    assert value.started_at == datetime(2026, 9, 5, tzinfo=UTC)
    assert value.attributes["arguments"]["amount"] == 80000
    with pytest.raises(TypeError):
        value.attributes["arguments"]["amount"] = 1


@pytest.mark.parametrize("field,value", [
    ("trace_id", "short"),
    ("trace_id", "A" * 32),
    ("span_id", "short"),
    ("span_id", "A" * 16),
    ("parent_span_id", "not-an-otel-id"),
])
def test_span_rejects_invalid_otel_ids(field, value):
    with pytest.raises(ValidationError):
        span(**{field: value})


def test_span_rejects_naive_or_reversed_timestamps():
    with pytest.raises(ValidationError, match="timezone-aware"):
        span(started_at=datetime(2026, 9, 5))
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="must not be before"):
        span(started_at=now, ended_at=now - timedelta(seconds=1))


def test_trace_enforces_span_identity_and_sequence_invariants():
    with pytest.raises(ValidationError, match="owning Trace trace_id"):
        Trace(
            trace_id=TRACE_ID,
            run_id="run",
            case_id="case",
            spans=(span(trace_id=OTHER_TRACE_ID),),
        )
    with pytest.raises(ValidationError, match="span_ids must be unique"):
        Trace(
            trace_id=TRACE_ID,
            run_id="run",
            case_id="case",
            spans=(span(), span(sequence=1)),
        )
    with pytest.raises(ValidationError, match="sequences must be unique"):
        Trace(
            trace_id=TRACE_ID,
            run_id="run",
            case_id="case",
            spans=(span(), span(span_id="2" * 16)),
        )


def test_trace_allows_missing_parent_and_selects_one_turn():
    trace = Trace(
        trace_id=TRACE_ID,
        run_id="run",
        case_id="case",
        spans=(
            span(
                operation_type="turn",
                attributes={"agentgate.turn.id": "first"},
            ),
            span(
                "2" * 16,
                1,
                operation_type="turn",
                attributes={"agentgate.turn.id": "second"},
            ),
            span("3" * 16, 2, parent_span_id="1" * 16),
        ),
        turn_outcomes={
            "first": {"input": {"message": "start"}, "output": {"reply": "ask"}, "state": {}},
            "second": {"input": {"amount": 10}, "output": {"reply": "done"}, "state": {"status": "ok"}},
        },
        final_output={"reply": "done"},
        final_state={"status": "ok"},
    )

    selected = trace.for_turn("first")
    assert [item.span_id for item in selected.spans] == ["1" * 16, "3" * 16]
    assert selected.final_output == {"reply": "ask"}
    assert selected.final_state == {}
    assert trace.completion_sequence() == 3
    with pytest.raises(ValueError, match="no outcome"):
        trace.for_turn("missing")
