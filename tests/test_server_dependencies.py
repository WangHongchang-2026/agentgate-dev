from __future__ import annotations

import pytest

from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import LOAN_AGENT_DESCRIPTORS
from agentgate.domain import RunStatus
from agentgate.server.dependencies import build_dependencies


class RecordingDispatcher:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)


def test_build_dependencies_seeds_isolated_demo_dataset(tmp_path) -> None:
    dependencies = build_dependencies(tmp_path / "server-dependencies.db")

    dataset = dependencies.datasets.get_dataset(LOAN_DATASET.id)
    version = dependencies.datasets.latest_published(dataset.id)

    assert dataset == LOAN_DATASET
    assert version.version == 1
    assert dependencies.targets.list_descriptors() == tuple(
        sorted(LOAN_AGENT_DESCRIPTORS, key=lambda item: item.content_sha256)
    )
    assert dependencies.results.list_runs() == []


def test_submit_demo_run_persists_then_dispatches_pending_run(tmp_path) -> None:
    dispatcher = RecordingDispatcher()
    dependencies = build_dependencies(
        tmp_path / "server-submit.db", dispatcher
    )

    run = dependencies.submit_demo_run(
        "loan-agent-v2-fixed",
        dataset_version=1,
        evaluator_ids=["skill-routing", "final-state"],
    )

    assert run.status is RunStatus.PENDING
    assert dependencies.repository.get_run(run.id) == run
    descriptor = dependencies.targets.resolve_descriptor(
        run.manifest.target.ref,
        run.manifest.target.descriptor_sha256,
    )
    assert descriptor.ref.external_version_id == "loan-agent-v2-fixed"
    assert dispatcher.run_ids == [run.id]


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
