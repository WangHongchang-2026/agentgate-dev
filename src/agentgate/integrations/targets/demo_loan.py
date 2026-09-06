"""Target adapter for the in-process deterministic Loan Agent demo."""

from __future__ import annotations

from typing import Any

from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from agentgate.demo.loan import LoanAgent
from agentgate.demo.provider import AgentProvider
from agentgate.domain import TargetType, canonical_json
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.run.target_protocol import (
    CaseExecutionRequest,
    CaseExecutionResult,
    CaseExecutionStatus,
    TargetExecutionError,
)


class DemoLoanTargetAdapter:
    """Translate one evaluation Case into Loan Agent invocations."""

    adapter_type = "demo_loan"
    adapter_version = "1"

    def __init__(
        self,
        capture: InMemoryTraceCapture,
        *,
        provider: AgentProvider | None = None,
        state_store: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.capture = capture
        self.provider = provider
        self.state_store = state_store if state_store is not None else {}
        self._statuses: dict[str, CaseExecutionStatus] = {}
        self._results: dict[str, CaseExecutionResult] = {}

    def start(self, request: CaseExecutionRequest) -> str:
        """Execute the local Agent synchronously and return its execution handle."""

        self._validate_request(request)
        handle = request.execution_id
        if handle in self._statuses:
            raise TargetExecutionError("invalid_request", "duplicate execution_id")

        self.capture.clear()
        self._statuses[handle] = CaseExecutionStatus.RUNNING
        trace_id = request.traceparent.split("-")[1]
        try:
            self._execute_case(request)
        except Exception as exc:
            self.capture.clear()
            self._statuses[handle] = CaseExecutionStatus.FAILED
            if isinstance(exc, TargetExecutionError):
                raise
            raise TargetExecutionError("rejected", type(exc).__name__) from exc

        result = CaseExecutionResult(execution_id=handle, trace_id=trace_id)
        self._results[handle] = result
        self._statuses[handle] = CaseExecutionStatus.COMPLETED
        return handle

    def get_status(self, handle: str) -> CaseExecutionStatus:
        """Return the local execution status."""

        return self._status(handle)

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult:
        """Return the result of an already completed synchronous execution."""

        if timeout_seconds <= 0:
            raise TargetExecutionError("invalid_request", "timeout must be positive")
        status = self._status(handle)
        if status is not CaseExecutionStatus.COMPLETED:
            raise TargetExecutionError(
                "protocol_error", f"execution is {status.value}, not completed"
            )
        return self._results[handle]

    def cancel(self, handle: str) -> None:
        """Cancel an execution that has not already reached a terminal state."""

        status = self._status(handle)
        if status in {
            CaseExecutionStatus.COMPLETED,
            CaseExecutionStatus.FAILED,
            CaseExecutionStatus.CANCELLED,
        }:
            return
        self._statuses[handle] = CaseExecutionStatus.CANCELLED
        self.capture.clear()

    def _execute_case(self, request: CaseExecutionRequest) -> None:
        tracer = self.capture.get_tracer("agentgate.demo.loan_adapter", self.adapter_version)
        parent = TraceContextTextMapPropagator().extract(
            {"traceparent": request.traceparent}
        )
        root_attributes = {
            "agentgate.run.id": request.run_id,
            "agentgate.case.id": request.case.id,
            "agentgate.execution.id": request.execution_id,
            "agentgate.operation.type": "case",
        }
        agent = LoanAgent(
            version=request.target.ref.external_version_id,
            tracer=self.capture.get_tracer("agentgate.demo.loan", "1"),
            provider=self.provider,
            state_store=self.state_store,
        )
        conversation_id: str | None = None
        final_output: dict[str, Any] = {}
        final_state: dict[str, Any] = {}

        with tracer.start_as_current_span(
            "case.execute", context=parent, attributes=root_attributes
        ) as case_span:
            for turn in request.case.turns:
                turn_input = turn.input.to_dict()
                with tracer.start_as_current_span(
                    "turn.execute",
                    attributes={
                        "agentgate.operation.type": "turn",
                        "agentgate.turn.id": turn.id,
                    },
                ) as turn_span:
                    response = agent.invoke(turn_input, conversation_id)
                    conversation_id = response.conversation_id
                    final_output = response.output
                    final_state = response.state
                    turn_span.set_attribute("agentgate.turn.complete", True)
                    turn_span.set_attribute(
                        "agentgate.turn.input", canonical_json(turn_input)
                    )
                    turn_span.set_attribute(
                        "agentgate.turn.output", canonical_json(final_output)
                    )
                    turn_span.set_attribute(
                        "agentgate.turn.state", canonical_json(final_state)
                    )

            case_span.set_attribute("agentgate.trace.complete", True)
            case_span.set_attribute(
                "agentgate.final.output", canonical_json(final_output)
            )
            case_span.set_attribute(
                "agentgate.final.state", canonical_json(final_state)
            )

    def _validate_request(self, request: CaseExecutionRequest) -> None:
        if request.target.ref.target_type is not TargetType.AGENT:
            raise TargetExecutionError("invalid_request", "demo target must be an Agent")
        if request.target.adapter_type != self.adapter_type:
            raise TargetExecutionError("invalid_request", "adapter_type does not match")
        if request.target.adapter_version != self.adapter_version:
            raise TargetExecutionError("invalid_request", "adapter_version does not match")
        if request.case.initial_state:
            raise TargetExecutionError(
                "invalid_request", "demo target does not support initial state seeding"
            )

    def _status(self, handle: str) -> CaseExecutionStatus:
        try:
            return self._statuses[handle]
        except KeyError as exc:
            raise TargetExecutionError("invalid_request", "unknown execution handle") from exc
