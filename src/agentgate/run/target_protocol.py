"""Runtime contract for executing one Case against a Target."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, TypeAlias, get_args

from agentgate.domain import Case, TargetSnapshot, Trace
from agentgate.domain.base import require_non_blank


_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_TRACEPARENT_PATTERN = re.compile(
    r"^(?!ff)[0-9a-f]{2}-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$"
)

TargetExecutionErrorCode: TypeAlias = Literal[
    "invalid_request",
    "target_not_found",
    "unauthorized",
    "rate_limited",
    "timeout",
    "unavailable",
    "rejected",
    "protocol_error",
]
_TARGET_EXECUTION_ERROR_CODES = frozenset(get_args(TargetExecutionErrorCode))


class CaseExecutionStatus(StrEnum):
    """Lifecycle status reported by a Target adapter."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class CaseExecutionRequest:
    """Normalized input for one Case execution within an EvaluationRun."""

    execution_id: str
    run_id: str
    case: Case
    target: TargetSnapshot
    timeout_seconds: float
    traceparent: str

    def __post_init__(self) -> None:
        require_non_blank(self.execution_id, "Case execution_id")
        require_non_blank(self.run_id, "Case run_id")
        if self.timeout_seconds <= 0:
            raise ValueError("Case timeout_seconds must be greater than zero")
        match = _TRACEPARENT_PATTERN.fullmatch(self.traceparent)
        if match is None or set(match.group(1)) == {"0"} or set(match.group(2)) == {"0"}:
            raise ValueError("traceparent must be a valid W3C Trace Context value")


@dataclass(frozen=True, slots=True)
class CaseExecutionResult:
    """Normalized completion result returned by a Target adapter."""

    execution_id: str
    trace_id: str
    inline_trace: Trace | None = None

    def __post_init__(self) -> None:
        require_non_blank(self.execution_id, "Case execution_id")
        if not _TRACE_ID_PATTERN.fullmatch(self.trace_id):
            raise ValueError(
                "trace_id must be exactly 32 lowercase hexadecimal characters"
            )
        if self.inline_trace is not None and self.inline_trace.trace_id != self.trace_id:
            raise ValueError("inline Trace must match Case execution trace_id")


class TargetExecutionError(RuntimeError):
    """Sanitized Target failure classified for execution and retry policy."""

    def __init__(self, code: TargetExecutionErrorCode, message: str) -> None:
        if code not in _TARGET_EXECUTION_ERROR_CODES:
            raise ValueError(f"unknown Target execution error code: {code}")
        self.code = code
        self.message = require_non_blank(message, "Target execution error message")
        super().__init__(f"{code}: {self.message}")


class TargetProtocol(Protocol):
    """Common lifecycle implemented by local and remote Target adapters."""

    adapter_type: str
    adapter_version: str

    def start(self, request: CaseExecutionRequest) -> str: ...

    def get_status(self, handle: str) -> CaseExecutionStatus: ...

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult: ...

    def cancel(self, handle: str) -> None: ...
