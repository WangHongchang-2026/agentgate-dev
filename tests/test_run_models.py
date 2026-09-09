from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agentgate.domain import (
    EvaluationRun, EvaluatorSpec, ReleaseGateSpec, MetricPlan, RunManifest, RunStatus,
    TargetRef, TargetSnapshot, TargetType, transition_run,
)
from agentgate.demo.loan import LOAN_DATASET_VERSION


def evaluator(evaluator_id: str = "state") -> EvaluatorSpec:
    return EvaluatorSpec(
        id=evaluator_id,
        name=evaluator_id,
        dimension="state",
        metric=f"{evaluator_id}_metric",
        implementation_id="final_state",
    )


def manifest(**overrides: object) -> RunManifest:
    values: dict[str, object] = {
        "dataset": LOAN_DATASET_VERSION,
        "target": TargetSnapshot(
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
        "evaluator_specs": (evaluator(),),
        "primary_evaluator_ids": ("state",),
        "metric_plan": MetricPlan(),
        "gate_spec": ReleaseGateSpec(),
        "created_at": datetime(2026, 9, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return RunManifest(**values)


def test_manifest_hash_excludes_creation_time() -> None:
    first = manifest()
    second = manifest(created_at=first.created_at + timedelta(hours=1))

    assert first.manifest_sha256 == second.manifest_sha256


def test_manifest_requires_unique_evaluators_and_valid_primary_ids() -> None:
    duplicate = evaluator()
    with pytest.raises(ValidationError, match="Evaluator ids must be unique"):
        manifest(evaluator_specs=(duplicate, duplicate))
    with pytest.raises(ValidationError, match="unknown Evaluators"):
        manifest(primary_evaluator_ids=("missing",))


def test_manifest_validates_execution_limits() -> None:
    with pytest.raises(ValidationError):
        manifest(timeout_seconds=0)
    with pytest.raises(ValidationError):
        manifest(max_retries=-1)
    with pytest.raises(ValidationError):
        manifest(max_parallel_cases=0)


def test_evaluation_run_follows_legal_lifecycle() -> None:
    created_at = datetime(2026, 9, 5, tzinfo=UTC)
    pending = EvaluationRun(manifest=manifest(), created_at=created_at)
    running = transition_run(
        pending, RunStatus.RUNNING, created_at + timedelta(seconds=1)
    )
    completed = transition_run(
        running, RunStatus.COMPLETED, created_at + timedelta(seconds=2)
    )

    assert running.started_at == created_at + timedelta(seconds=1)
    assert completed.completed_at == created_at + timedelta(seconds=2)
    assert completed.error is None


def test_scheduled_run_releases_only_at_its_requested_time() -> None:
    created_at = datetime(2026, 9, 5, tzinfo=UTC)
    scheduled_for = created_at + timedelta(hours=1)
    scheduled = EvaluationRun(
        manifest=manifest(),
        status=RunStatus.SCHEDULED,
        created_at=created_at,
        scheduled_for=scheduled_for,
    )

    with pytest.raises(ValueError, match="cannot be released before"):
        transition_run(
            scheduled,
            RunStatus.PENDING,
            scheduled_for - timedelta(seconds=1),
        )

    pending = transition_run(scheduled, RunStatus.PENDING, scheduled_for)
    assert pending.status is RunStatus.PENDING
    assert pending.scheduled_for == scheduled_for


def test_scheduled_run_requires_a_future_timezone_aware_time() -> None:
    created_at = datetime(2026, 9, 5, tzinfo=UTC)
    with pytest.raises(ValidationError, match="requires scheduled_for"):
        EvaluationRun(
            manifest=manifest(),
            status=RunStatus.SCHEDULED,
            created_at=created_at,
        )
    with pytest.raises(ValidationError, match="later than created_at"):
        EvaluationRun(
            manifest=manifest(),
            status=RunStatus.SCHEDULED,
            created_at=created_at,
            scheduled_for=created_at,
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        EvaluationRun(
            manifest=manifest(),
            status=RunStatus.SCHEDULED,
            created_at=created_at,
            scheduled_for=datetime(2026, 9, 6),
        )


def test_failed_transition_requires_error() -> None:
    run = EvaluationRun(manifest=manifest())

    with pytest.raises(ValueError, match="requires an error"):
        transition_run(run, RunStatus.FAILED)
    failed = transition_run(run, RunStatus.FAILED, error="dispatch failed")
    assert failed.error == "dispatch failed"


def test_terminal_run_cannot_transition_again() -> None:
    run = EvaluationRun(manifest=manifest())
    cancelled = transition_run(run, RunStatus.CANCELLED)

    with pytest.raises(ValueError, match="illegal Run transition"):
        transition_run(cancelled, RunStatus.RUNNING)


def test_run_rejects_inconsistent_direct_state() -> None:
    with pytest.raises(ValidationError, match="running.*started_at"):
        EvaluationRun(manifest=manifest(), status=RunStatus.RUNNING)
    created_at = datetime(2026, 9, 5, tzinfo=UTC)
    with pytest.raises(ValidationError, match="failed.*error"):
        EvaluationRun(
            manifest=manifest(),
            status=RunStatus.FAILED,
            created_at=created_at,
            completed_at=created_at + timedelta(seconds=1),
        )


def test_run_normalizes_timestamps_and_rejects_naive_values() -> None:
    local_time = datetime(2026, 9, 5, 8, tzinfo=timezone(timedelta(hours=8)))
    run = EvaluationRun(manifest=manifest(), created_at=local_time)
    assert run.created_at == datetime(2026, 9, 5, tzinfo=UTC)

    with pytest.raises(ValidationError, match="timezone-aware"):
        EvaluationRun(manifest=manifest(), created_at=datetime(2026, 9, 5))
