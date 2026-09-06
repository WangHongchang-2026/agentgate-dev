"""Execute an immutable EvaluationRun through a Target adapter."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from uuid import uuid4

from agentgate.domain import (
    Case,
    EvaluationResult,
    EvaluationRun,
    EvaluatorSpec,
    RunStatus,
    Trace,
    transition_run,
)
from agentgate.storage.repository import AgentGateRepository

from .target_protocol import (
    CaseExecutionRequest,
    CaseExecutionResult,
    CaseExecutionStatus,
    TargetExecutionError,
    TargetAdapterProtocol,
)


LOGGER = logging.getLogger(__name__)

CaseEvaluator = Callable[
    [Case, Trace, tuple[EvaluatorSpec, ...]], Sequence[EvaluationResult]
]
TraceResolver = Callable[[CaseExecutionRequest, CaseExecutionResult], Trace]


class RunEngine:
    """Execute all Cases pinned by one persisted pending EvaluationRun."""

    def __init__(
        self,
        repository: AgentGateRepository,
        evaluate_case: CaseEvaluator,
        resolve_trace: TraceResolver,
    ) -> None:
        self.repository = repository
        self.evaluate_case = evaluate_case
        self.resolve_trace = resolve_trace

    def execute(
        self, run: EvaluationRun, target_adapter: TargetAdapterProtocol
    ) -> EvaluationRun:
        self._require_persisted_pending(run)
        running = transition_run(run, RunStatus.RUNNING)
        self.repository.save_run(running)
        active_handle: str | None = None

        try:
            self._validate_execution(running, target_adapter)
            results: list[EvaluationResult] = []
            for case in running.manifest.dataset.cases:
                request = self._build_request(running, case)
                active_handle = target_adapter.start(request)
                if not active_handle.strip():
                    raise TargetExecutionError(
                        "protocol_error", "Target returned a blank execution handle"
                    )
                outcome = target_adapter.wait(active_handle, request.timeout_seconds)
                status = target_adapter.get_status(active_handle)
                if status == CaseExecutionStatus.CANCELLED:
                    raise TargetExecutionError(
                        "cancelled", "Target execution was cancelled"
                    )
                if status != CaseExecutionStatus.COMPLETED:
                    raise TargetExecutionError(
                        "protocol_error",
                        f"Target wait returned while execution status was {status.value}",
                    )
                active_handle = None
                trace = self.resolve_trace(request, outcome)
                self._validate_trace(request, outcome, trace)
                self.repository.save_trace(trace)
                case_results = tuple(
                    self.evaluate_case(
                        case, trace, running.manifest.evaluator_specs
                    )
                )
                self._validate_results(running, case, trace, case_results)
                results.extend(case_results)

            self.repository.save_results(results)
            completed = transition_run(running, RunStatus.COMPLETED)
            self.repository.save_run(completed)
            return completed
        except Exception as exc:
            if active_handle is not None:
                self._cancel(target_adapter, active_handle)
            terminal_status = (
                RunStatus.CANCELLED
                if isinstance(exc, TargetExecutionError) and exc.code == "cancelled"
                else RunStatus.FAILED
            )
            error = None if terminal_status == RunStatus.CANCELLED else self._safe_error(exc)
            terminal = transition_run(running, terminal_status, error=error)
            self.repository.save_run(terminal)
            raise

    def _require_persisted_pending(self, run: EvaluationRun) -> None:
        if run.status != RunStatus.PENDING:
            raise ValueError("RunEngine requires a pending EvaluationRun")
        stored = self.repository.get_run(run.id)
        if stored is None:
            raise ValueError("EvaluationRun must be persisted before execution")
        if stored != run:
            raise ValueError("persisted EvaluationRun does not match execution request")

    @staticmethod
    def _validate_execution(
        run: EvaluationRun, target_adapter: TargetAdapterProtocol
    ) -> None:
        manifest = run.manifest
        if manifest.max_retries != 0:
            raise ValueError("RunEngine retry support is not implemented")
        if manifest.max_parallel_cases != 1:
            raise ValueError("RunEngine parallel Case execution is not implemented")
        if target_adapter.adapter_type != manifest.target.adapter_type:
            raise ValueError("Target adapter_type does not match RunManifest")
        if target_adapter.adapter_version != manifest.target.adapter_version:
            raise ValueError("Target adapter_version does not match RunManifest")

    @staticmethod
    def _build_request(run: EvaluationRun, case: Case) -> CaseExecutionRequest:
        trace_id = uuid4().hex
        parent_span_id = uuid4().hex[:16]
        return CaseExecutionRequest(
            execution_id=str(uuid4()),
            run_id=run.id,
            case=case,
            target=run.manifest.target,
            timeout_seconds=run.manifest.timeout_seconds,
            traceparent=f"00-{trace_id}-{parent_span_id}-01",
        )

    @staticmethod
    def _validate_trace(
        request: CaseExecutionRequest,
        outcome: CaseExecutionResult,
        trace: Trace,
    ) -> None:
        if outcome.execution_id != request.execution_id:
            raise ValueError("Target result execution_id does not match request")
        if trace.trace_id != outcome.trace_id:
            raise ValueError("resolved Trace does not match Target result trace_id")
        if trace.run_id != request.run_id:
            raise ValueError("resolved Trace does not match EvaluationRun")
        if trace.case_id != request.case.id:
            raise ValueError("resolved Trace does not match Case")

    @staticmethod
    def _validate_results(
        run: EvaluationRun,
        case: Case,
        trace: Trace,
        results: tuple[EvaluationResult, ...],
    ) -> None:
        expected = {spec.id: spec for spec in run.manifest.evaluator_specs}
        actual_ids = tuple(result.evaluator_id for result in results)
        if len(set(actual_ids)) != len(actual_ids):
            raise ValueError("Evaluator returned duplicate EvaluationResults")
        if set(actual_ids) != set(expected):
            raise ValueError("Evaluator did not return exactly one Result per specification")

        for result in results:
            spec = expected[result.evaluator_id]
            if (
                result.run_id != run.id
                or result.case_id != case.id
                or result.trace_id != trace.trace_id
            ):
                raise ValueError("EvaluationResult execution identity does not match")
            if (
                result.evaluator_name != spec.name
                or result.evaluator_version != spec.version
                or result.evaluator_content_sha256 != spec.content_sha256
                or result.evaluator_kind != spec.kind
                or result.dimension != spec.dimension
                or result.metric != spec.metric
                or result.severity != spec.severity
            ):
                raise ValueError("EvaluationResult does not match EvaluatorSpec")

    @staticmethod
    def _cancel(target_adapter: TargetAdapterProtocol, handle: str) -> None:
        try:
            target_adapter.cancel(handle)
        except Exception as exc:
            LOGGER.warning(
                "Target cancellation failed with %s", type(exc).__name__
            )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, TargetExecutionError):
            return str(exc)
        return type(exc).__name__
