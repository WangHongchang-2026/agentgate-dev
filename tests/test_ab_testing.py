from __future__ import annotations

import pytest

from agentgate.application.ab_testing import ABRunPair, create_ab_runs
from agentgate.application.evaluator_management import (
    build_default_evaluator_management,
)
from agentgate.application.run_management import RunManagement
from agentgate.application.target_catalog import TargetCatalog
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import EvaluatorRef, RunStatus, TargetRef, TargetSnapshot
from agentgate.storage.sqlite import SQLiteRepository


class RecordingDispatcher:
    def __init__(self, fail_calls: set[int] | None = None) -> None:
        self.fail_calls = fail_calls or set()
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)
        if len(self.run_ids) in self.fail_calls:
            raise ConnectionError("dispatcher unavailable")


def _target(version: str) -> TargetSnapshot:
    return build_demo_target_snapshot(get_demo_target_descriptor(version))


def _management(repository: SQLiteRepository) -> RunManagement:
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    return RunManagement(
        repository,
        build_default_evaluator_management(repository),
    )


def test_create_ab_runs_persists_and_dispatches_one_controlled_pair(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "ab-runs.db")
    management = _management(repository)
    dispatcher = RecordingDispatcher()

    pair = create_ab_runs(
        management,
        dispatcher,
        _target("loan-agent-v1-risky"),
        _target("loan-agent-v2-fixed"),
        dataset_id=LOAN_DATASET.id,
        dataset_version=1,
        evaluator_refs=(
            EvaluatorRef(evaluator_id="skill-routing", evaluator_version="1"),
            EvaluatorRef(evaluator_id="final-state", evaluator_version="1"),
        ),
        timeout_seconds=30,
    )

    assert pair.baseline_run.id != pair.candidate_run.id
    assert dispatcher.run_ids == [
        pair.baseline_run.id,
        pair.candidate_run.id,
    ]
    assert pair.baseline_run.status is RunStatus.PENDING
    assert pair.candidate_run.status is RunStatus.PENDING
    assert repository.get_run(pair.baseline_run.id) == pair.baseline_run
    assert repository.get_run(pair.candidate_run.id) == pair.candidate_run
    assert pair.baseline_run.manifest.dataset == pair.candidate_run.manifest.dataset
    assert (
        pair.baseline_run.manifest.evaluator_specs
        == pair.candidate_run.manifest.evaluator_specs
    )


def test_create_ab_runs_rejects_same_version_before_persisting(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "same-version.db")
    management = _management(repository)
    snapshot = _target("loan-agent-v2-fixed")

    with pytest.raises(ValueError, match="different Agent versions"):
        create_ab_runs(
            management,
            RecordingDispatcher(),
            snapshot,
            snapshot,
            dataset_id=LOAN_DATASET.id,
        )

    assert repository.list_runs() == []


def test_create_ab_runs_rejects_different_agent_before_persisting(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "different-agent.db")
    management = _management(repository)
    candidate = _target("loan-agent-v2-fixed")
    unrelated = TargetSnapshot(
        ref=TargetRef(
            source_id=candidate.ref.source_id,
            target_type=candidate.ref.target_type,
            external_target_id="another-agent",
            external_version_id=candidate.ref.external_version_id,
        ),
        display_name=candidate.display_name,
        adapter_type=candidate.adapter_type,
        adapter_version=candidate.adapter_version,
        descriptor_sha256=candidate.descriptor_sha256,
        invocation_config=candidate.invocation_config,
    )

    with pytest.raises(ValueError, match="same logical Agent"):
        create_ab_runs(
            management,
            RecordingDispatcher(),
            _target("loan-agent-v1-risky"),
            unrelated,
            dataset_id=LOAN_DATASET.id,
        )

    assert repository.list_runs() == []


def test_create_ab_runs_preflights_both_descriptors_before_persisting(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "descriptor-preflight.db")
    ensure_demo_dataset(repository)
    catalog = TargetCatalog(repository)
    baseline_descriptor = get_demo_target_descriptor("loan-agent-v1-risky")
    catalog.register_descriptor(baseline_descriptor)
    management = RunManagement(
        repository,
        build_default_evaluator_management(repository),
    )

    with pytest.raises(LookupError, match="unknown TargetDescriptor"):
        create_ab_runs(
            management,
            RecordingDispatcher(),
            build_demo_target_snapshot(baseline_descriptor),
            _target("loan-agent-v2-fixed"),
            dataset_id=LOAN_DATASET.id,
        )

    assert repository.list_runs() == []


def test_create_ab_runs_dispatches_candidate_after_baseline_failure(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "partial-dispatch.db")
    management = _management(repository)
    dispatcher = RecordingDispatcher(fail_calls={1})

    pair = create_ab_runs(
        management,
        dispatcher,
        _target("loan-agent-v1-risky"),
        _target("loan-agent-v2-fixed"),
        dataset_id=LOAN_DATASET.id,
    )

    assert dispatcher.run_ids == [
        pair.baseline_run.id,
        pair.candidate_run.id,
    ]
    assert pair.baseline_run.status is RunStatus.FAILED
    assert pair.baseline_run.error == "Run dispatch failed: ConnectionError"
    assert pair.candidate_run.status is RunStatus.PENDING


def test_ab_run_pair_rejects_duplicate_run_identity(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "duplicate-pair.db")
    management = _management(repository)
    run = management.create_run(
        _target("loan-agent-v1-risky"),
        dataset_id=LOAN_DATASET.id,
    )

    with pytest.raises(ValueError, match="distinct identities"):
        ABRunPair(baseline_run=run, candidate_run=run)
