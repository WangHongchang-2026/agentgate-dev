from __future__ import annotations

import json

import pytest
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from agentgate.domain import Case, CaseTurn, TargetRef, TargetSnapshot, TargetType
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.run.target_protocol import CaseExecutionRequest, CaseExecutionResult


TRACE_ID = "a" * 32


def request(execution_id: str = "execution-1") -> CaseExecutionRequest:
    case = Case(
        id="case-1",
        name="Case",
        turns=(CaseTurn(id="turn-1", input={"message": "hello"}),),
    )
    target = TargetSnapshot(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="v1",
        ),
        display_name="Loan Agent",
        adapter_type="demo-loan",
        adapter_version="1",
        descriptor_sha256="a" * 64,
    )
    return CaseExecutionRequest(
        execution_id=execution_id,
        run_id="run-1",
        case=case,
        target=target,
        timeout_seconds=10,
        traceparent=f"00-{TRACE_ID}-{'b' * 16}-01",
    )


def emit_complete_trace(capture: InMemoryTraceCapture, value: CaseExecutionRequest) -> None:
    tracer = capture.get_tracer("tests", "1")
    parent = TraceContextTextMapPropagator().extract(
        {"traceparent": value.traceparent}
    )
    common = {
        "agentgate.run.id": value.run_id,
        "agentgate.case.id": value.case.id,
        "agentgate.execution.id": value.execution_id,
    }
    with tracer.start_as_current_span(
        "case.execute", context=parent, attributes=common
    ) as root:
        with tracer.start_as_current_span(
            "turn.execute",
            attributes={
                "agentgate.turn.id": "turn-1",
                "agentgate.operation.type": "turn",
            },
        ) as turn:
            with tracer.start_as_current_span(
                "route",
                attributes={
                    "agentgate.turn.id": "turn-1",
                    "agentgate.operation.type": "routing",
                },
            ) as routing:
                routing.set_status(Status(StatusCode.OK))
            turn.set_attribute("agentgate.turn.complete", True)
            turn.set_attribute(
                "agentgate.turn.input", json.dumps({"message": "hello"})
            )
            turn.set_attribute(
                "agentgate.turn.output", json.dumps({"reply": "approved"})
            )
            turn.set_attribute(
                "agentgate.turn.state", json.dumps({"status": "approved"})
            )
        root.set_attribute("agentgate.operation.type", "case")
        root.set_attribute("agentgate.trace.complete", True)
        root.set_attribute(
            "agentgate.final.output", json.dumps({"reply": "approved"})
        )
        root.set_attribute(
            "agentgate.final.state", json.dumps({"status": "approved"})
        )


def test_resolve_builds_complete_domain_trace_from_real_sdk_spans() -> None:
    capture = InMemoryTraceCapture()
    value = request()
    emit_complete_trace(capture, value)

    trace = capture.resolve(value, CaseExecutionResult(value.execution_id, TRACE_ID))

    assert trace.trace_id == TRACE_ID
    assert trace.run_id == "run-1"
    assert trace.case_id == "case-1"
    assert [span.operation_type for span in trace.spans] == ["case", "turn", "routing"]
    assert "agentgate.run.id" not in trace.spans[1].attributes
    assert "agentgate.execution.id" not in trace.spans[2].attributes
    assert trace.turn_outcomes["turn-1"]["output"] == {"reply": "approved"}
    assert trace.final_state == {"status": "approved"}
    capture.shutdown()


def test_resolve_rejects_wrong_execution_and_clears_capture() -> None:
    capture = InMemoryTraceCapture()
    value = request()
    emit_complete_trace(capture, value)
    wrong = request("execution-2")

    with pytest.raises(ValueError, match="execution_id"):
        capture.resolve(wrong, CaseExecutionResult(wrong.execution_id, TRACE_ID))

    with pytest.raises(ValueError, match="no completed spans"):
        capture.resolve(value, CaseExecutionResult(value.execution_id, TRACE_ID))
    capture.shutdown()


def test_capture_rejects_inline_trace_and_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        InMemoryTraceCapture(max_spans=0)

    capture = InMemoryTraceCapture()
    with pytest.raises(ValueError, match="tracer name"):
        capture.get_tracer(" ")
    value = request()
    emit_complete_trace(capture, value)
    trace = capture.resolve(value, CaseExecutionResult(value.execution_id, TRACE_ID))
    emit_complete_trace(capture, value)

    with pytest.raises(ValueError, match="inline Trace"):
        capture.resolve(
            value,
            CaseExecutionResult(value.execution_id, TRACE_ID, inline_trace=trace),
        )
    with pytest.raises(ValueError, match="no completed spans"):
        capture.resolve(value, CaseExecutionResult(value.execution_id, TRACE_ID))
    capture.shutdown()
