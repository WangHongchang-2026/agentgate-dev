from __future__ import annotations

import pytest

from agentgate.demo.loan import LOAN_DATASET
from agentgate.domain import RunStatus
from agentgate.server.dependencies import build_dependencies


def test_build_dependencies_seeds_isolated_demo_dataset(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "server-dependencies.db")

    dataset = dependencies.datasets.get_dataset(LOAN_DATASET.id)
    version = dependencies.datasets.latest_published(dataset.id)

    assert dataset == LOAN_DATASET
    assert version.version == 1
    assert dependencies.results.list_runs() == []


def test_execute_demo_run_uses_new_application_and_otel_runtime(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "server-run.db")

    run = dependencies.execute_demo_run(
        "loan-agent-v2-fixed",
        dataset_version=1,
        evaluator_ids=["skill-routing", "final-state"],
    )

    report = dependencies.results.get_report(run.id)
    assert run.status is RunStatus.COMPLETED
    assert [result.evaluator_id for result in report.results] == [
        "final-state", "skill-routing"
    ]
    assert report.release_gate.outcome.value == "pass"
    assert dependencies.demo_state["A-100"]["status"] == "pending_review"


def test_execute_demo_run_rejects_unknown_version_before_creating_run(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "invalid-server-run.db")

    with pytest.raises(ValueError, match="unknown demo Target version"):
        dependencies.execute_demo_run("missing-version")

    assert dependencies.results.list_runs() == []
