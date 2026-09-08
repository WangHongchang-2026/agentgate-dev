"""Execute an immutable EvaluationRun through a Target adapter."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from uuid import uuid4

from agentgate.domain import (
    Case,
    EvaluationResult,
    EvaluationRun,
    EvaluatorSpec,
    RunStatus,
    Trace,
    transition_run,
    utcnow,
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
ActiveCase = tuple[Case, CaseExecutionRequest, str]


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
        stored = self._require_persisted_run(run)
        if stored.status is not RunStatus.PENDING:
            return stored
        running = self.repository.claim_pending_run(run.id, utcnow())
        if running is None:
            claimed = self.repository.get_run(run.id)
            if claimed is None:
                raise ValueError("EvaluationRun disappeared while being claimed")
            return claimed

        try:
            self._validate_execution(running, target_adapter)
            self._execute_cases(running, target_adapter)

            completed = transition_run(running, RunStatus.COMPLETED)
            self.repository.save_run(completed)
            return completed
        except Exception as exc:
            terminal_status = (
                RunStatus.CANCELLED
                if isinstance(exc, TargetExecutionError) and exc.code == "cancelled"
                else RunStatus.FAILED
            )
            error = None if terminal_status == RunStatus.CANCELLED else self._safe_error(exc)
            terminal = transition_run(running, terminal_status, error=error)
            self.repository.save_run(terminal)
            raise

    def _execute_cases(
        self,
        run: EvaluationRun,
        target_adapter: TargetAdapterProtocol,
    ) -> None:
        pending_cases = iter(run.manifest.dataset.cases)
        active: deque[ActiveCase] = deque()
        exhausted = False

        try:
            while active or not exhausted:
                while not exhausted and len(active) < run.manifest.max_parallel_cases:
                    try:
                        case = next(pending_cases)
                    except StopIteration:
                        exhausted = True
                        break

                    request, handle = self._start_case(run, case, target_adapter)
                    active.append((case, request, handle))
                    status = target_adapter.get_status(handle)
                    if status not in {
                        CaseExecutionStatus.PENDING,
                        CaseExecutionStatus.RUNNING,
                    }:
                        break

                if not active:
                    continue

                case, request, handle = active[0]
                self._complete_case(run, case, request, handle, target_adapter)
                active.popleft()
        except Exception:
            self._cancel_active(target_adapter, active)
            raise

    def _start_case(
        self,
        run: EvaluationRun,
        case: Case,
        target_adapter: TargetAdapterProtocol,
    ) -> tuple[CaseExecutionRequest, str]:
        request = self._build_request(run, case)
        handle = target_adapter.start(request)
        if not handle.strip():
            raise TargetExecutionError(
                "protocol_error", "Target returned a blank execution handle"
            )
        return request, handle

    def _complete_case(
        self,
        run: EvaluationRun,
        case: Case,
        request: CaseExecutionRequest,
        handle: str,
        target_adapter: TargetAdapterProtocol,
    ) -> None:
        outcome = target_adapter.wait(handle, request.timeout_seconds)
        status = target_adapter.get_status(handle)
        if status == CaseExecutionStatus.CANCELLED:
            raise TargetExecutionError("cancelled", "Target execution was cancelled")
        if status != CaseExecutionStatus.COMPLETED:
            raise TargetExecutionError(
                "protocol_error",
                f"Target wait returned while execution status was {status.value}",
            )
        trace = self.resolve_trace(request, outcome)
        self._validate_trace(request, outcome, trace)
        self.repository.save_trace(trace)
        case_results = tuple(
            self.evaluate_case(case, trace, run.manifest.evaluator_specs)
        )
        self._validate_results(run, case, trace, case_results)
        self.repository.save_results(case_results)

    @classmethod
    def _cancel_active(
        cls,
        target_adapter: TargetAdapterProtocol,
        active: Iterable[ActiveCase],
    ) -> None:
        for _, _, handle in active:
            cls._cancel(target_adapter, handle)

    def _require_persisted_run(self, run: EvaluationRun) -> EvaluationRun:
        if run.status != RunStatus.PENDING:
            raise ValueError("RunEngine requires a pending EvaluationRun")
        stored = self.repository.get_run(run.id)
        if stored is None:
            raise ValueError("EvaluationRun must be persisted before execution")
        if stored.status is RunStatus.PENDING and stored != run:
            raise ValueError("persisted EvaluationRun does not match execution request")
        return stored

    @staticmethod
    def _validate_execution(
        run: EvaluationRun, target_adapter: TargetAdapterProtocol
    ) -> None:
        manifest = run.manifest
        if manifest.max_retries != 0:
            raise ValueError("RunEngine retry support is not implemented")
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
