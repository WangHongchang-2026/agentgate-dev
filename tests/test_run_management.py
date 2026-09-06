from __future__ import annotations

import pytest

from agentgate.application import RunManagement
from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import (
    RunStatus,
    TargetRef,
    TargetSnapshot,
    TargetType,
)
from agentgate.evaluator import EVALUATORS
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.sqlite import SQLiteRepository


def target(version: str = "loan-agent-v2-fixed") -> TargetSnapshot:
    return TargetSnapshot(
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
        invocation_config={"provider": "deterministic"},
    )


def test_create_run_persists_exact_pending_manifest(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "create-run.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)

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


def test_execute_run_uses_engine_adapter_and_trace_resolver(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "execute-run.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)
    run = management.create_run(target(), dataset_id=LOAN_DATASET.id)
    capture = InMemoryTraceCapture()
    adapter = DemoLoanTargetAdapter(capture)

    completed = management.execute_run(run.id, adapter, capture.resolve)

    assert completed.status is RunStatus.COMPLETED
    assert len(repository.list_traces(run.id)) == 1
    results = repository.list_results(run.id)
    assert len(results) == len(EVALUATORS)
    assert all(result.outcome.value not in {"fail", "review", "error"}
               for result in results)
    capture.shutdown()


def test_create_run_rejects_unknown_or_duplicate_evaluators(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "invalid-run.db")
    ensure_demo_dataset(repository)
    management = RunManagement(repository, EVALUATORS)

    with pytest.raises(ValueError, match="unknown Evaluators"):
        management.create_run(
            target(), dataset_id=LOAN_DATASET.id, evaluator_ids=("missing",)
        )
    with pytest.raises(ValueError, match="must be unique"):
        management.create_run(
            target(),
            dataset_id=LOAN_DATASET.id,
            evaluator_ids=("final-state", "final-state"),
        )


def test_execute_run_rejects_unknown_run(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "missing-run.db")
    management = RunManagement(repository, EVALUATORS)
    capture = InMemoryTraceCapture()

    with pytest.raises(ValueError, match="unknown EvaluationRun"):
        management.execute_run(
            "missing", DemoLoanTargetAdapter(capture), capture.resolve
        )
    capture.shutdown()
