from dataclasses import FrozenInstanceError

import pytest

from agentgate.domain import (
    Case,
    CaseTurn,
    TargetRef,
    TargetSnapshot,
    TargetType,
    Trace,
    content_sha256,
)
from agentgate.run.target_protocol import (
    CaseExecutionRequest,
    CaseExecutionResult,
    TargetExecutionError,
)


TRACE_ID = "1" * 32
TRACEPARENT = f"00-{TRACE_ID}-{'2' * 16}-01"


def target() -> TargetSnapshot:
    return TargetSnapshot(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id="v1",
        ),
        display_name="Loan Agent",
        adapter_type="python_function",
        adapter_version="1",
        descriptor_sha256=content_sha256({"target": "loan-agent"}),
    )


def case() -> Case:
    return Case(name="Loan request", turns=(CaseTurn(input={"amount": 1000}),))


def request(**overrides: object) -> CaseExecutionRequest:
    values = {
        "execution_id": "execution-1",
        "run_id": "run-1",
        "case": case(),
        "target": target(),
        "timeout_seconds": 30.0,
        "traceparent": TRACEPARENT,
    }
    values.update(overrides)
    return CaseExecutionRequest(**values)


def test_case_execution_request_is_immutable() -> None:
    value = request()

    with pytest.raises(FrozenInstanceError):
        value.run_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["execution_id", "run_id"])
def test_case_execution_request_rejects_blank_identity(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        request(**{field: " "})


def test_case_execution_request_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        request(timeout_seconds=0)


@pytest.mark.parametrize(
    "traceparent",
    [
        "invalid",
        f"00-{'0' * 32}-{'2' * 16}-01",
        f"00-{TRACE_ID}-{'0' * 16}-01",
        f"FF-{TRACE_ID}-{'2' * 16}-01",
    ],
)
def test_case_execution_request_rejects_invalid_traceparent(traceparent: str) -> None:
    with pytest.raises(ValueError, match="W3C Trace Context"):
        request(traceparent=traceparent)


def test_case_execution_result_accepts_matching_inline_trace() -> None:
    trace = Trace(
        trace_id=TRACE_ID,
        run_id="run-1",
        case_id=case().id,
        spans=(),
    )

    result = CaseExecutionResult("execution-1", TRACE_ID, trace)

    assert result.inline_trace is trace


def test_case_execution_result_rejects_mismatched_inline_trace() -> None:
    trace = Trace(
        trace_id="3" * 32,
        run_id="run-1",
        case_id=case().id,
        spans=(),
    )

    with pytest.raises(ValueError, match="must match"):
        CaseExecutionResult("execution-1", TRACE_ID, trace)


def test_target_execution_error_exposes_typed_code_and_sanitized_message() -> None:
    error = TargetExecutionError(
        "timeout", "Agent did not finish; api_key=secret-value"
    )

    assert error.code == "timeout"
    assert error.message == "Agent did not finish; api_key=[redacted]"
    assert "secret-value" not in str(error)


def test_target_execution_error_rejects_unknown_code() -> None:
    with pytest.raises(ValueError, match="unknown Target execution error code"):
        TargetExecutionError("typo", "Agent failed")  # type: ignore[arg-type]
