from __future__ import annotations

from datetime import timedelta

import pytest

from agentgate.application import RunManagement, TargetCatalog
from agentgate.application.evaluator_management import (
    EvaluatorCatalogConflict,
    EvaluatorManagement,
    build_default_evaluator_management,
)
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import (
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
    RunStatus,
    TargetSnapshot,
)
from agentgate.evaluator.models import DuplicateEvaluatorId, UnknownEvaluator
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.sqlite import SQLiteRepository


class RecordingDispatcher:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if self.failure is not None:
            raise self.failure


def target(version: str = "loan-agent-v2-fixed") -> TargetSnapshot:
    return build_demo_target_snapshot(
        get_demo_target_descriptor(version)
    )


def seed_demo(repository: SQLiteRepository) -> None:
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))


def run_management(
    repository: SQLiteRepository,
) -> tuple[RunManagement, EvaluatorManagement]:
    evaluators = build_default_evaluator_management(repository)
    return RunManagement(repository, evaluators), evaluators


def test_create_run_persists_exact_pending_manifest(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "create-run.db")
    seed_demo(repository)
    management, _ = run_management(repository)

    run = management.create_run(
        target(),
        dataset_id=LOAN_DATASET.id,
        dataset_version=1,
        evaluator_ids=("skill-routing", "final-state"),
        timeout_seconds=30,
    )

    assert run.status is RunStatus.PENDING
    assert repository.get_run(run.id) == run
    assert [spec.id for spec in run.manifest.evaluator_specs] == [
        "skill-routing", "final-state"
    ]
    assert run.manifest.target.ref.external_version_id == "loan-agent-v2-fixed"
    assert run.manifest.timeout_seconds == 30
    assert run.manifest.max_parallel_cases == 1


def test_create_run_persists_case_concurrency_limit(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "create-parallel-run.db")
    seed_demo(repository)
    management, _ = run_management(repository)

    run = management.create_run(
        target(),
        dataset_id=LOAN_DATASET.id,
        max_parallel_cases=4,
    )

    assert run.manifest.max_parallel_cases == 4
    assert repository.get_run(run.id) == run

    with pytest.raises(ValueError, match="max_parallel_cases"):
        management.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            max_parallel_cases=0,
        )


def test_create_run_snapshots_latest_enabled_user_evaluator_version(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "user-evaluator-run.db")
    seed_demo(repository)
    runs, evaluators = run_management(repository)
    evaluator, _ = evaluators.create_evaluator(
        "Custom output",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="custom_output_v1",
        implementation_id="final_output",
        config={},
    )

    with pytest.raises(EvaluatorCatalogConflict, match="disabled"):
        runs.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            evaluator_ids=(evaluator.id,),
        )

    first = evaluators.publish_draft(evaluator.id)
    with pytest.raises(EvaluatorCatalogConflict, match="disabled"):
        runs.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            evaluator_ids=(evaluator.id,),
        )

    evaluators.update_evaluator(evaluator.id, enabled=True)
    first_run = runs.create_run(
        target(),
        dataset_id=LOAN_DATASET.id,
        evaluator_ids=(evaluator.id,),
    )
    assert first_run.manifest.evaluator_specs == (first,)

    evaluators.create_draft(evaluator.id)
    evaluators.replace_draft(
        evaluator.id,
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="custom_output_v2",
        severity=EvaluatorSeverity.BLOCKING,
        implementation_id="final_output",
        implementation_version="1",
        config={},
        children=(),
        combination=None,
    )
    second = evaluators.publish_draft(evaluator.id)
    evaluators.update_evaluator(evaluator.id, enabled=False)

    stored_first_run = repository.get_run(first_run.id)
    assert stored_first_run is not None
    assert stored_first_run.manifest.evaluator_specs == (first,)
    with pytest.raises(EvaluatorCatalogConflict, match="disabled"):
        runs.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            evaluator_ids=(evaluator.id,),
        )

    evaluators.update_evaluator(evaluator.id, enabled=True)
    second_run = runs.create_run(
        target(),
        dataset_id=LOAN_DATASET.id,
        evaluator_ids=(evaluator.id,),
    )
    assert second.version == "2"
    assert second_run.manifest.evaluator_specs == (second,)


def test_create_run_selects_an_exact_historical_evaluator_version(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "exact-evaluator-run.db")
    seed_demo(repository)
    runs, evaluators = run_management(repository)
    evaluator, _ = evaluators.create_evaluator(
        "Versioned output",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="versioned_output_v1",
        implementation_id="final_output",
        config={},
    )
    first = evaluators.publish_draft(evaluator.id)
    evaluators.update_evaluator(evaluator.id, enabled=True)
    evaluators.create_draft(evaluator.id)
    evaluators.replace_draft(
        evaluator.id,
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="versioned_output_v2",
        severity=EvaluatorSeverity.BLOCKING,
        implementation_id="final_output",
        implementation_version="1",
        config={},
        children=(),
        combination=None,
    )
    second = evaluators.publish_draft(evaluator.id)

    run = runs.create_run(
        target(),
        dataset_id=LOAN_DATASET.id,
        evaluator_refs=(
            EvaluatorRef(
                evaluator_id=evaluator.id,
                evaluator_version=first.version,
            ),
        ),
    )

    assert second.version == "2"
    assert run.manifest.evaluator_specs == (first,)


def test_execute_run_uses_engine_adapter_and_trace_resolver(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "execute-run.db")
    seed_demo(repository)
    management, evaluators = run_management(repository)
    run = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    capture = InMemoryTraceCapture()
    adapter = DemoLoanTargetAdapter(capture)

    completed = management.execute_run(run.id, adapter, capture.resolve)

    assert completed.status is RunStatus.COMPLETED
    assert len(repository.list_traces(run.id)) == 1
    results = repository.list_results(run.id)
    assert len(results) == len(evaluators.default_specs)
    assert all(result.outcome.value not in {"fail", "review", "error"}
               for result in results)
    capture.shutdown()


def test_create_run_rejects_unknown_or_duplicate_evaluators(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "invalid-run.db")
    seed_demo(repository)
    management, _ = run_management(repository)

    with pytest.raises(UnknownEvaluator, match="unknown Evaluator: missing"):
        management.create_run(
            target(), dataset_id=LOAN_DATASET.id, evaluator_ids=("missing",)
        )
    with pytest.raises(DuplicateEvaluatorId, match="must be unique"):
        management.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            evaluator_ids=("final-state", "final-state"),
        )
    with pytest.raises(DuplicateEvaluatorId, match="must be unique"):
        management.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            evaluator_refs=(
                EvaluatorRef(
                    evaluator_id="final-state",
                    evaluator_version="1",
                ),
                EvaluatorRef(
                    evaluator_id="final-state",
                    evaluator_version="1",
                ),
            ),
        )


def test_execute_run_rejects_unknown_run(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "missing-run.db")
    management, _ = run_management(repository)
    capture = InMemoryTraceCapture()

    with pytest.raises(ValueError, match="unknown EvaluationRun"):
        management.execute_run(
            "missing", DemoLoanTargetAdapter(capture), capture.resolve
        )
    capture.shutdown()


def test_create_run_requires_persisted_matching_target_descriptor(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "missing-target-descriptor.db")
    ensure_demo_dataset(repository)
    management, _ = run_management(repository)
    fixed = target()

    with pytest.raises(LookupError, match="unknown TargetDescriptor"):
        management.create_run(fixed, dataset_id=LOAN_DATASET.id)

    fixed_descriptor = get_demo_target_descriptor("loan-agent-v2-fixed")
    TargetCatalog(repository).register_descriptor(fixed_descriptor)
    risky_ref = get_demo_target_descriptor("loan-agent-v1-risky").ref
    mismatched = TargetSnapshot(
        ref=risky_ref,
        display_name=fixed.display_name,
        adapter_type=fixed.adapter_type,
        adapter_version=fixed.adapter_version,
        descriptor_sha256=fixed.descriptor_sha256,
        invocation_config=fixed.invocation_config,
    )
    with pytest.raises(ValueError, match="does not match TargetSnapshot"):
        management.create_run(mismatched, dataset_id=LOAN_DATASET.id)

    assert repository.list_runs() == []


def test_dispatch_run_submits_only_the_persisted_run_id(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "dispatch-run.db")
    seed_demo(repository)
    management, _ = run_management(repository)
    run = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    dispatcher = RecordingDispatcher()

    dispatched = management.dispatch_run(run.id, dispatcher)

    assert dispatched == run
    assert dispatcher.run_ids == [run.id]
    assert repository.get_run(run.id).status is RunStatus.PENDING


def test_dispatch_failure_is_persisted_without_exception_details(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "dispatch-failure.db")
    seed_demo(repository)
    management, _ = run_management(repository)
    run = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    dispatcher = RecordingDispatcher(
        ConnectionError("redis://user:secret@example.invalid")
    )

    with pytest.raises(RuntimeError, match="Run dispatch failed"):
        management.dispatch_run(run.id, dispatcher)

    failed = repository.get_run(run.id)
    assert failed.status is RunStatus.FAILED
    assert failed.error == "Run dispatch failed: ConnectionError"
    assert "secret" not in failed.error


def test_fail_stale_runs_preserves_active_and_pending_runs(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "stale-runs.db")
    seed_demo(repository)
    management, _ = run_management(repository)
    stale = management.create_run(
        target(), dataset_id=LOAN_DATASET.id, timeout_seconds=10
    )
    active = management.create_run(
        target(), dataset_id=LOAN_DATASET.id, timeout_seconds=10
    )
    pending = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    now = max(stale.created_at, active.created_at, pending.created_at) + timedelta(
        seconds=100
    )
    repository.claim_pending_run(stale.id, now - timedelta(seconds=20))
    repository.claim_pending_run(active.id, now - timedelta(seconds=5))

    failed = management.fail_stale_runs(now=now, grace_seconds=5)

    assert [run.id for run in failed] == [stale.id]
    assert repository.get_run(stale.id).status is RunStatus.FAILED
    assert repository.get_run(active.id).status is RunStatus.RUNNING
    assert repository.get_run(pending.id).status is RunStatus.PENDING


def test_fail_stale_runs_accounts_for_parallel_case_batches(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "parallel-stale-runs.db")
    seed_demo(repository)
    management, _ = run_management(repository)
    dataset, draft = management.dataset_management.copy_dataset(
        LOAN_DATASET.id,
        "Four cases",
    )
    source_case_id = draft.cases[0].id
    for _ in range(3):
        management.dataset_management.copy_case(dataset.id, source_case_id)
    management.dataset_management.publish_draft(dataset.id)

    sequential = management.create_run(
        target(),
        dataset_id=dataset.id,
        dataset_version=1,
        timeout_seconds=10,
        max_parallel_cases=1,
    )
    parallel = management.create_run(
        target(),
        dataset_id=dataset.id,
        dataset_version=1,
        timeout_seconds=10,
        max_parallel_cases=2,
    )
    now = max(sequential.created_at, parallel.created_at) + timedelta(seconds=100)
    started_at = now - timedelta(seconds=30)
    repository.claim_pending_run(sequential.id, started_at)
    repository.claim_pending_run(parallel.id, started_at)

    failed = management.fail_stale_runs(now=now, grace_seconds=5)

    assert [run.id for run in failed] == [parallel.id]
    assert repository.get_run(sequential.id).status is RunStatus.RUNNING
    assert repository.get_run(parallel.id).status is RunStatus.FAILED


def test_fail_stale_runs_rejects_negative_grace_period(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "invalid-grace.db")
    management, _ = run_management(repository)

    with pytest.raises(ValueError, match="must not be negative"):
        management.fail_stale_runs(grace_seconds=-1)
