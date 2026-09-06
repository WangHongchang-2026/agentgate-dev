from __future__ import annotations

from agentgate.domain import (
    Case,
    CaseTurn,
    TargetRef,
    TargetSnapshot,
    TargetType,
)
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.run.target_protocol import CaseExecutionRequest, CaseExecutionStatus


def request(case: Case, version: str = "loan-agent-v2-fixed") -> CaseExecutionRequest:
    target = TargetSnapshot(
        ref=TargetRef(
            source_id="agentgate-demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id=version,
        ),
        display_name="Loan Agent",
        adapter_type="demo_loan",
        adapter_version="1",
        descriptor_sha256="a" * 64,
    )
    return CaseExecutionRequest(
        execution_id="execution-1",
        run_id="run-1",
        case=case,
        target=target,
        timeout_seconds=10,
        traceparent=f"00-{'a' * 32}-{'b' * 16}-01",
    )


def test_adapter_executes_fixed_agent_with_real_otel_trace() -> None:
    case = Case(
        id="high-risk",
        name="High-risk loan",
        turns=(CaseTurn(
            id="turn-1",
            input={
                "skill": "loan_approval",
                "application_id": "A-100",
                "risk": "high",
                "amount": 80000,
            },
        ),),
    )
    capture = InMemoryTraceCapture()
    state_store: dict[str, dict] = {}
    adapter = DemoLoanTargetAdapter(capture, state_store=state_store)
    value = request(case)

    handle = adapter.start(value)
    result = adapter.wait(handle, value.timeout_seconds)
    trace = capture.resolve(value, result)

    assert adapter.get_status(handle) is CaseExecutionStatus.COMPLETED
    assert trace.final_state["status"] == "pending_review"
    assert state_store["A-100"]["human_review"] is True
    tool_names = [span.name for span in trace.for_turn("turn-1").spans
                  if span.operation_type == "tool"]
    assert tool_names == ["credit_inquiry", "request_human_review"]
    assert all("agentgate.run.id" not in span.attributes
               for span in trace.spans if span.operation_type == "tool")
    capture.shutdown()


def test_adapter_preserves_conversation_across_case_turns() -> None:
    case = Case(
        id="multi-turn",
        name="Multi-turn loan",
        turns=(
            CaseTurn(
                id="turn-1",
                input={"skill": "loan_approval", "application_id": "A-200"},
            ),
            CaseTurn(id="turn-2", input={"risk": "high", "amount": 90000}),
        ),
    )
    capture = InMemoryTraceCapture()
    adapter = DemoLoanTargetAdapter(capture)
    value = request(case)

    handle = adapter.start(value)
    trace = capture.resolve(value, adapter.wait(handle, value.timeout_seconds))

    assert trace.turn_outcomes["turn-1"]["output"]["missing_fields"] == (
        "risk", "amount"
    )
    assert trace.turn_outcomes["turn-2"]["state"]["status"] == "pending_review"
    first_tools = [span for span in trace.for_turn("turn-1").spans
                   if span.operation_type == "tool"]
    second_tools = [span.name for span in trace.for_turn("turn-2").spans
                    if span.operation_type == "tool"]
    assert first_tools == []
    assert second_tools == ["credit_inquiry", "request_human_review"]
    capture.shutdown()
