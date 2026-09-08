from __future__ import annotations

import sqlite3

import pytest

from agentgate.application import RunManagement, TargetCatalog
from agentgate.application.evaluator_management import (
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
from agentgate.domain import RunStatus, TargetType, content_sha256, transition_run
from agentgate.storage.sqlite import SQLiteRepository


def create_demo_run(repository: SQLiteRepository, version: str):
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    descriptor = get_demo_target_descriptor(version)
    evaluators = build_default_evaluator_management(repository)
    return RunManagement(repository, evaluators).create_run(
        build_demo_target_snapshot(descriptor),
        dataset_id=LOAN_DATASET.id,
    )


def test_run_asset_references_support_exact_reverse_queries(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "reverse-lineage.db")
    baseline = create_demo_run(repository, "loan-agent-v1-risky")
    candidate = create_demo_run(repository, "loan-agent-v2-fixed")
    dataset = candidate.manifest.dataset
    case = dataset.cases[0]
    evaluator = candidate.manifest.evaluator_specs[0]

    assert {
        run.id
        for run in repository.list_runs_by_dataset_version(
            dataset.dataset_id, dataset.version
        )
    } == {baseline.id, candidate.id}
    assert {
        run.id
        for run in repository.list_runs_by_case_content(
            dataset.dataset_id,
            dataset.version,
            case.id,
            content_sha256(case),
        )
    } == {baseline.id, candidate.id}
    assert repository.list_runs_by_target_version(
        "agentgate-demo",
        TargetType.AGENT,
        "loan-agent",
        "loan-agent-v2-fixed",
    ) == [candidate]
    assert repository.list_runs_by_skill_version(
        "agentgate-demo",
        "loan_approval",
        "loan-approval-v2-fixed",
    ) == [candidate]
    assert {
        run.id
        for run in repository.list_runs_by_evaluator_version(
            evaluator.id, evaluator.version
        )
    } == {baseline.id, candidate.id}


def test_run_asset_references_are_created_once(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "stable-lineage.db")
    run = create_demo_run(repository, "loan-agent-v2-fixed")
    with sqlite3.connect(repository.path) as database:
        initial_count = database.execute(
            "SELECT COUNT(*) FROM run_asset_refs WHERE run_id=?", (run.id,)
        ).fetchone()[0]

    running = transition_run(run, RunStatus.RUNNING)
    repository.save_run(running)

    with sqlite3.connect(repository.path) as database:
        final_count = database.execute(
            "SELECT COUNT(*) FROM run_asset_refs WHERE run_id=?", (run.id,)
        ).fetchone()[0]
    expected_count = (
        1
        + len(run.manifest.dataset.cases)
        + 1
        + len(get_demo_target_descriptor("loan-agent-v2-fixed").skills)
        + len(run.manifest.evaluator_specs)
    )
    assert initial_count == final_count == expected_count


def test_reverse_queries_apply_limits_and_exact_versions(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "limited-lineage.db")
    first = create_demo_run(repository, "loan-agent-v2-fixed")
    second = create_demo_run(repository, "loan-agent-v2-fixed")
    dataset = second.manifest.dataset

    limited = repository.list_runs_by_dataset_version(
        dataset.dataset_id, dataset.version, limit=1
    )
    assert len(limited) == 1
    assert limited[0].id in {first.id, second.id}
    assert repository.list_runs_by_dataset_version(
        dataset.dataset_id, dataset.version + 1
    ) == []
    with pytest.raises(ValueError, match="limit must be at least 1"):
        repository.list_runs_by_dataset_version(
            dataset.dataset_id, dataset.version, limit=0
        )
