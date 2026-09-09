import json
import sqlite3
from datetime import timedelta

import pytest

from agentgate.application.evaluator_management import (
    build_default_evaluator_management,
)
from agentgate.domain import (
    Case, CaseTurn, ReleaseGateSpec, MetricPlan, EvaluationRun, RunManifest, TargetRef,
    RunStatus, TargetSnapshot, TargetType, transition_run,
)
from agentgate.demo.loan import LOAN_DATASET_VERSION
from agentgate.storage.sqlite import SQLiteRepository


def manifest(repository: SQLiteRepository):
    evaluator_specs = build_default_evaluator_management(repository).default_specs
    return RunManifest(
        dataset=LOAN_DATASET_VERSION,
        target=TargetSnapshot(
            ref=TargetRef(
                source_id="demo",
                target_type=TargetType.AGENT,
                external_target_id="loan",
                external_version_id="v1",
            ),
            display_name="loan",
            adapter_type="python_function",
            adapter_version="1",
            descriptor_sha256="a" * 64,
        ),
        evaluator_specs=evaluator_specs,
        primary_evaluator_ids=tuple(item.id for item in evaluator_specs),
        metric_plan=MetricPlan(),
        gate_spec=ReleaseGateSpec(),
    )


def test_manifest_is_deeply_immutable_and_hash_is_stable(tmp_path):
    repository = SQLiteRepository(tmp_path / "manifest.db")
    first = manifest(repository)
    second = RunManifest.model_validate(first.model_dump(mode="json"))
    assert first.manifest_sha256 == second.manifest_sha256
    with pytest.raises(TypeError):
        first.dataset.cases[0].turns[0].input["risk"] = "low"


def test_mutating_source_data_cannot_change_domain_content():
    source = {"nested": [{"risk": "high"}]}
    case = Case(
        id="case", name="case",
        turns=(CaseTurn(id="turn", input=source),),
    )
    source["nested"][0]["risk"] = "low"
    assert case.turns[0].input["nested"][0]["risk"] == "high"


def test_repository_rejects_tampered_manifest(tmp_path):
    repository = SQLiteRepository(tmp_path / "tamper.db")
    run = EvaluationRun(manifest=manifest(repository))
    repository.save_run(run)
    with sqlite3.connect(repository.path) as db:
        payload = json.loads(db.execute(
            "SELECT payload FROM runs WHERE id=?", (run.id,)
        ).fetchone()[0])
        payload["manifest"]["target"]["ref"]["external_version_id"] = "tampered"
        db.execute("UPDATE runs SET payload=? WHERE id=?", (json.dumps(payload), run.id))
    with pytest.raises(ValueError, match="hash mismatch"):
        repository.get_run(run.id)


def test_repository_preserves_run_identity_and_terminal_state(tmp_path):
    repository = SQLiteRepository(tmp_path / "run-lifecycle.db")
    pending = EvaluationRun(id="run", manifest=manifest(repository))
    repository.save_run(pending)

    changed_creation = pending.model_copy(
        update={"created_at": pending.created_at + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="created_at is immutable"):
        repository.save_run(changed_creation)

    changed_manifest = pending.model_copy(
        update={
            "manifest": manifest(repository).model_copy(
                update={"created_at": pending.created_at}
            )
        }
    )
    with pytest.raises(ValueError, match="manifest is immutable"):
        repository.save_run(changed_manifest)

    running = transition_run(
        pending, RunStatus.RUNNING, occurred_at=pending.created_at + timedelta(seconds=1)
    )
    repository.save_run(running)
    changed_start = running.model_copy(
        update={"started_at": running.started_at + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="started_at is immutable"):
        repository.save_run(changed_start)

    completed = transition_run(
        running, RunStatus.COMPLETED, occurred_at=running.started_at + timedelta(seconds=1)
    )
    repository.save_run(completed)
    repository.save_run(completed)
    with pytest.raises(ValueError, match="terminal EvaluationRun is immutable"):
        repository.save_run(running)
    assert repository.get_run(pending.id) == completed


def test_repository_lists_runs_with_valid_limit_and_deterministic_ties(tmp_path):
    repository = SQLiteRepository(tmp_path / "run-list.db")
    first = EvaluationRun(id="b-run", manifest=manifest(repository))
    second = EvaluationRun(
        id="a-run",
        manifest=manifest(repository),
        created_at=first.created_at,
    )
    repository.save_run(first)
    repository.save_run(second)

    assert [run.id for run in repository.list_runs()] == ["a-run", "b-run"]
    assert [run.id for run in repository.list_runs(limit=1)] == ["a-run"]
    with pytest.raises(ValueError, match="limit must be at least 1"):
        repository.list_runs(limit=0)


def test_repository_claims_a_pending_run_once(tmp_path):
    repository = SQLiteRepository(tmp_path / "run-claim.db")
    pending = EvaluationRun(id="run", manifest=manifest(repository))
    repository.save_run(pending)
    started_at = pending.created_at + timedelta(seconds=1)

    claimed = repository.claim_pending_run(pending.id, started_at)

    assert claimed is not None
    assert claimed.status is RunStatus.RUNNING
    assert claimed.started_at == started_at
    assert repository.get_run(pending.id) == claimed
    assert repository.claim_pending_run(pending.id, started_at) is None
    assert repository.claim_pending_run("missing", started_at) is None


def test_repository_atomically_cancels_pending_run(tmp_path):
    repository = SQLiteRepository(tmp_path / "cancel-pending.db")
    pending = EvaluationRun(id="run", manifest=manifest(repository))
    repository.save_run(pending)
    cancelled_at = pending.created_at + timedelta(seconds=1)

    cancelled = repository.cancel_run(pending.id, cancelled_at)

    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.started_at is None
    assert cancelled.completed_at == cancelled_at
    assert repository.get_run(pending.id) == cancelled
    assert repository.cancel_run(pending.id, cancelled_at) is None
    assert repository.claim_pending_run(pending.id, cancelled_at) is None


def test_repository_atomically_cancels_running_run(tmp_path):
    repository = SQLiteRepository(tmp_path / "cancel-running.db")
    pending = EvaluationRun(id="run", manifest=manifest(repository))
    repository.save_run(pending)
    started_at = pending.created_at + timedelta(seconds=1)
    running = repository.claim_pending_run(pending.id, started_at)
    assert running is not None
    cancelled_at = started_at + timedelta(seconds=1)

    cancelled = repository.cancel_run(pending.id, cancelled_at)

    assert cancelled is not None
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.started_at == started_at
    assert cancelled.completed_at == cancelled_at
    assert repository.get_run(pending.id) == cancelled


def test_repository_cancellation_rejects_ineligible_runs_and_time(tmp_path):
    repository = SQLiteRepository(tmp_path / "cancel-ineligible.db")
    completed_pending = EvaluationRun(
        id="completed",
        manifest=manifest(repository),
    )
    failed_pending = EvaluationRun(
        id="failed",
        manifest=manifest(repository),
    )
    invalid_time = EvaluationRun(
        id="invalid-time",
        manifest=manifest(repository),
    )
    for run in (completed_pending, failed_pending, invalid_time):
        repository.save_run(run)

    completed_running = transition_run(
        completed_pending,
        RunStatus.RUNNING,
        occurred_at=completed_pending.created_at + timedelta(seconds=1),
    )
    completed = transition_run(
        completed_running,
        RunStatus.COMPLETED,
        occurred_at=completed_running.started_at + timedelta(seconds=1),
    )
    failed_running = transition_run(
        failed_pending,
        RunStatus.RUNNING,
        occurred_at=failed_pending.created_at + timedelta(seconds=1),
    )
    failed = transition_run(
        failed_running,
        RunStatus.FAILED,
        occurred_at=failed_running.started_at + timedelta(seconds=1),
        error="Target failed",
    )
    repository.save_run(completed)
    repository.save_run(failed)

    assert repository.cancel_run("missing", completed.completed_at) is None
    assert repository.cancel_run(completed.id, completed.completed_at) is None
    assert repository.cancel_run(failed.id, failed.completed_at) is None
    with pytest.raises(ValueError, match="precede Run activity"):
        repository.cancel_run(
            invalid_time.id,
            invalid_time.created_at - timedelta(seconds=1),
        )

    assert repository.get_run(completed.id) == completed
    assert repository.get_run(failed.id) == failed
    assert repository.get_run(invalid_time.id) == invalid_time


def test_repository_lists_and_counts_runs_by_status(tmp_path):
    repository = SQLiteRepository(tmp_path / "run-status.db")
    first = EvaluationRun(id="first", manifest=manifest(repository))
    second = EvaluationRun(
        id="second",
        manifest=manifest(repository),
        created_at=first.created_at + timedelta(seconds=1),
    )
    repository.save_run(first)
    repository.save_run(second)
    repository.claim_pending_run(second.id, second.created_at + timedelta(seconds=1))

    assert [
        run.id
        for run in repository.list_runs_by_status(
            RunStatus.PENDING, oldest_first=True
        )
    ] == ["first"]
    assert [
        run.id for run in repository.list_runs_by_status(RunStatus.RUNNING, limit=1)
    ] == ["second"]
    assert repository.count_runs_by_status() == {
        RunStatus.PENDING: 1,
        RunStatus.RUNNING: 1,
        RunStatus.COMPLETED: 0,
        RunStatus.FAILED: 0,
        RunStatus.CANCELLED: 0,
    }
    with pytest.raises(ValueError, match="limit must be at least 1"):
        repository.list_runs_by_status(RunStatus.PENDING, limit=0)
