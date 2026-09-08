from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agentgate.application import ResultReader, RunManagement, TargetCatalog
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
from agentgate.domain import EvaluationReport, EvaluationRun
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter
from agentgate.storage.sqlite import SQLiteRepository


DemoExecution = Callable[..., tuple[EvaluationRun, EvaluationReport]]


@pytest.fixture
def execute_demo() -> DemoExecution:
    """Execute the deterministic demo through current application boundaries."""

    def execute(
        repository: SQLiteRepository,
        version: str,
        *,
        dataset_id: str = LOAN_DATASET.id,
        dataset_version: int | None = None,
        evaluator_ids: list[str] | None = None,
        state_store: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[EvaluationRun, EvaluationReport]:
        ensure_demo_dataset(repository)
        target_catalog = TargetCatalog(repository)
        ensure_demo_target_descriptors(target_catalog)
        target = build_demo_target_snapshot(
            get_demo_target_descriptor(version)
        )
        evaluators = build_default_evaluator_management(repository)
        runs = RunManagement(repository, evaluators)
        run = runs.create_run(
            target,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            evaluator_ids=evaluator_ids,
        )
        capture = InMemoryTraceCapture()
        try:
            completed = runs.execute_run(
                run.id,
                DemoLoanTargetAdapter(capture, state_store=state_store),
                capture.resolve,
            )
        finally:
            capture.shutdown()
        return completed, ResultReader(repository).get_report(completed.id)

    return execute
