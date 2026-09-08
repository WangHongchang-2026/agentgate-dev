from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentgate.domain import (
    Case,
    CaseTurn,
    CheckResult,
    DatasetVersion,
    EvaluationResult,
    EvaluationRun,
    EvaluatorSpec,
    MetricPlan,
    Outcome,
    ReleaseGateSpec,
    RunManifest,
    RunStatus,
    TargetRef,
    TargetSnapshot,
    TargetType,
    Trace,
)
from agentgate.run.engine import RunEngine
from agentgate.run.target_protocol import (
    CaseExecutionRequest,
    CaseExecutionResult,
    CaseExecutionStatus,
    TargetExecutionError,
)
from agentgate.storage.sqlite import SQLiteRepository


class StubTargetAdapter:
    adapter_type = "stub"
    adapter_version = "1"

    def __init__(self, failure: TargetExecutionError | None = None) -> None:
        self.failure = failure
        self.requests: dict[str, CaseExecutionRequest] = {}
        self.cancelled: list[str] = []

    def start(self, request: CaseExecutionRequest) -> str:
        self.requests[request.execution_id] = request
        return request.execution_id

    def get_status(self, handle: str) -> CaseExecutionStatus:
        return CaseExecutionStatus.COMPLETED

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult:
        if self.failure is not None:
            raise self.failure
        request = self.requests[handle]
        trace_id = request.traceparent.split("-")[1]
        trace = Trace(
            trace_id=trace_id,
            run_id=request.run_id,
            case_id=request.case.id,
            spans=(),
        )
        return CaseExecutionResult(request.execution_id, trace_id, trace)

    def cancel(self, handle: str) -> None:
        self.cancelled.append(handle)


class FailOnCaseTargetAdapter(StubTargetAdapter):
    def __init__(self, case_id: str) -> None:
        super().__init__()
        self.case_id = case_id

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult:
        if self.requests[handle].case.id == self.case_id:
            raise TargetExecutionError("unavailable", "Target failed")
        return super().wait(handle, timeout_seconds)


class WindowedTargetAdapter(StubTargetAdapter):
    def __init__(self, failure_handle_index: int | None = None) -> None:
        super().__init__()
        self.failure_handle_index = failure_handle_index
        self.statuses: dict[str, CaseExecutionStatus] = {}
        self.active_count = 0
        self.max_active_count = 0

    def start(self, request: CaseExecutionRequest) -> str:
        handle = super().start(request)
        self.statuses[handle] = CaseExecutionStatus.RUNNING
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        return handle

    def get_status(self, handle: str) -> CaseExecutionStatus:
        return self.statuses[handle]

    def wait(self, handle: str, timeout_seconds: float) -> CaseExecutionResult:
        handle_index = tuple(self.requests).index(handle)
        if handle_index == self.failure_handle_index:
            raise TargetExecutionError("unavailable", "Target failed")
        self.statuses[handle] = CaseExecutionStatus.COMPLETED
        self.active_count -= 1
        return super().wait(handle, timeout_seconds)

    def cancel(self, handle: str) -> None:
        if self.statuses[handle] == CaseExecutionStatus.RUNNING:
            self.statuses[handle] = CaseExecutionStatus.CANCELLED
            self.active_count -= 1
        super().cancel(handle)


def evaluator_spec() -> EvaluatorSpec:
    return EvaluatorSpec(
        id="final-output",
        name="Final output",
        dimension="answer",
        metric="final_output_match",
        implementation_id="final_output",
    )


def pending_run(
    *, cases: tuple[Case, ...] | None = None, **manifest_overrides: object
) -> EvaluationRun:
    default_case = Case(
        id="case-1",
        name="Case",
        turns=(CaseTurn(id="turn-1", input={"message": "hello"}),),
    )
    dataset = DatasetVersion(
        id="dataset-version-1",
        dataset_id="dataset-1",
        version=1,
        status="published",
        cases=cases or (default_case,),
        created_at=datetime(2026, 9, 6, tzinfo=UTC),
        updated_at=datetime(2026, 9, 6, tzinfo=UTC),
        published_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    target = TargetSnapshot(
        ref=TargetRef(
            source_id="demo",
            target_type=TargetType.AGENT,
            external_target_id="agent-1",
            external_version_id="v1",
        ),
        display_name="Agent",
        adapter_type="stub",
        adapter_version="1",
        descriptor_sha256="a" * 64,
    )
    values = {
        "dataset": dataset,
        "target": target,
        "evaluator_specs": (evaluator_spec(),),
        "primary_evaluator_ids": ("final-output",),
        "metric_plan": MetricPlan(),
        "gate_spec": ReleaseGateSpec(),
    }
    values.update(manifest_overrides)
    return EvaluationRun(id="run-1", manifest=RunManifest(**values))


def evaluate_case(case, trace, specs):
    spec = specs[0]
    return (
        EvaluationResult(
            id=f"result-{case.id}",
            run_id=trace.run_id,
            case_id=case.id,
            trace_id=trace.trace_id,
            evaluator_id=spec.id,
            evaluator_name=spec.name,
            evaluator_version=spec.version,
            evaluator_content_sha256=spec.content_sha256,
            evaluator_kind=spec.kind,
            dimension=spec.dimension,
            metric=spec.metric,
            severity=spec.severity,
            outcome=Outcome.PASS,
            score=1,
            reason="Matched",
            checks=(
                CheckResult(
                    id=f"check-{case.id}",
                    name="Output",
                    outcome=Outcome.PASS,
                    score=1,
                    reason="Matched",
                ),
            ),
        ),
    )


def resolve_trace(request, result):
    assert result.execution_id == request.execution_id
    assert result.inline_trace is not None
    return result.inline_trace


def engine(repository) -> RunEngine:
    return RunEngine(repository, evaluate_case, resolve_trace)


def test_engine_executes_persisted_pending_run(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "engine.db")
    run = pending_run()
    repository.save_run(run)
    target_adapter = StubTargetAdapter()

    completed = engine(repository).execute(run, target_adapter)

    assert completed.status == RunStatus.COMPLETED
    assert repository.get_run(run.id) == completed
    assert len(repository.list_traces(run.id)) == 1
    assert len(repository.list_results(run.id)) == 1
    request = next(iter(target_adapter.requests.values()))
    assert request.run_id == run.id
    assert request.case.id == "case-1"
    assert request.target == run.manifest.target


def test_engine_does_not_execute_a_run_twice(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "duplicate.db")
    run = pending_run()
    repository.save_run(run)
    target_adapter = StubTargetAdapter()

    completed = engine(repository).execute(run, target_adapter)
    duplicate = engine(repository).execute(run, target_adapter)

    assert duplicate == completed
    assert len(target_adapter.requests) == 1


def test_engine_preserves_completed_case_results_when_later_case_fails(
    tmp_path,
) -> None:
    repository = SQLiteRepository(tmp_path / "partial-results.db")
    cases = (
        Case(
            id="case-1",
            name="First",
            turns=(CaseTurn(id="turn-1", input={"message": "first"}),),
        ),
        Case(
            id="case-2",
            name="Second",
            turns=(CaseTurn(id="turn-2", input={"message": "second"}),),
        ),
    )
    run = pending_run(cases=cases)
    repository.save_run(run)

    with pytest.raises(TargetExecutionError, match="unavailable"):
        engine(repository).execute(run, FailOnCaseTargetAdapter("case-2"))

    assert [result.case_id for result in repository.list_results(run.id)] == [
        "case-1"
    ]
    assert repository.get_run(run.id).status is RunStatus.FAILED


def test_engine_limits_active_cases_to_manifest_configuration(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "parallel.db")
    cases = tuple(
        Case(
            id=f"case-{index}",
            name=f"Case {index}",
            turns=(
                CaseTurn(
                    id=f"turn-{index}",
                    input={"message": f"message {index}"},
                ),
            ),
        )
        for index in range(1, 6)
    )
    run = pending_run(cases=cases, max_parallel_cases=2)
    repository.save_run(run)
    target_adapter = WindowedTargetAdapter()

    completed = engine(repository).execute(run, target_adapter)

    assert completed.status is RunStatus.COMPLETED
    assert target_adapter.max_active_count == 2
    assert target_adapter.active_count == 0
    assert len(repository.list_traces(run.id)) == 5
    assert len(repository.list_results(run.id)) == 5


def test_engine_cancels_all_active_cases_after_parallel_failure(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "parallel-failure.db")
    cases = tuple(
        Case(
            id=f"case-{index}",
            name=f"Case {index}",
            turns=(CaseTurn(id=f"turn-{index}", input={"message": "hello"}),),
        )
        for index in range(1, 5)
    )
    run = pending_run(cases=cases, max_parallel_cases=3)
    repository.save_run(run)
    target_adapter = WindowedTargetAdapter(failure_handle_index=0)

    with pytest.raises(TargetExecutionError, match="unavailable"):
        engine(repository).execute(run, target_adapter)

    assert target_adapter.max_active_count == 3
    assert target_adapter.active_count == 0
    assert len(target_adapter.cancelled) == 3
    assert repository.get_run(run.id).status is RunStatus.FAILED


def test_engine_requires_run_to_be_persisted(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "missing.db")

    with pytest.raises(ValueError, match="persisted before execution"):
        engine(repository).execute(pending_run(), StubTargetAdapter())


def test_engine_fails_closed_for_unsupported_retry(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "retry.db")
    run = pending_run(max_retries=1)
    repository.save_run(run)

    with pytest.raises(ValueError, match="retry support"):
        engine(repository).execute(run, StubTargetAdapter())

    failed = repository.get_run(run.id)
    assert failed is not None
    assert failed.status == RunStatus.FAILED


def test_engine_rejects_adapter_version_mismatch(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "adapter.db")
    run = pending_run()
    repository.save_run(run)
    target_adapter = StubTargetAdapter()
    target_adapter.adapter_version = "2"

    with pytest.raises(ValueError, match="adapter_version"):
        engine(repository).execute(run, target_adapter)

    assert target_adapter.requests == {}
    assert repository.get_run(run.id).status == RunStatus.FAILED


def test_engine_rejects_incomplete_evaluator_output(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "results.db")
    run = pending_run()
    repository.save_run(run)
    incomplete = RunEngine(repository, lambda case, trace, specs: (), resolve_trace)

    with pytest.raises(ValueError, match="exactly one Result"):
        incomplete.execute(run, StubTargetAdapter())

    assert repository.list_results(run.id) == []
    assert repository.get_run(run.id).status == RunStatus.FAILED


def test_engine_cancels_active_target_and_sanitizes_failure(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "failure.db")
    run = pending_run()
    repository.save_run(run)
    target_adapter = StubTargetAdapter(
        TargetExecutionError("timeout", "token=secret-value")
    )

    with pytest.raises(TargetExecutionError, match="timeout"):
        engine(repository).execute(run, target_adapter)

    failed = repository.get_run(run.id)
    assert failed is not None
    assert failed.status == RunStatus.FAILED
    assert "secret-value" not in failed.error
    assert target_adapter.cancelled == [next(iter(target_adapter.requests))]


def test_engine_records_target_cancellation(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "cancelled.db")
    run = pending_run()
    repository.save_run(run)
    target_adapter = StubTargetAdapter(
        TargetExecutionError("cancelled", "Cancelled by user")
    )

    with pytest.raises(TargetExecutionError, match="cancelled"):
        engine(repository).execute(run, target_adapter)

    cancelled = repository.get_run(run.id)
    assert cancelled is not None
    assert cancelled.status == RunStatus.CANCELLED
    assert cancelled.error is None
