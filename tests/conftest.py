from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from agentgate.application import ResultReader, RunManagement
from agentgate.application.evaluator_management import DEFAULT_EVALUATOR_MANAGEMENT
from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET, LoanAgent
from agentgate.domain import (
    EvaluationReport,
    EvaluationRun,
    TargetRef,
    TargetSnapshot,
    TargetType,
    content_sha256,
)
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
        target = TargetSnapshot(
            ref=TargetRef(
                source_id="agentgate-demo",
                target_type=TargetType.AGENT,
                external_target_id="loan-agent",
                external_version_id=version,
            ),
            display_name="Loan Agent",
            adapter_type=DemoLoanTargetAdapter.adapter_type,
            adapter_version=DemoLoanTargetAdapter.adapter_version,
            descriptor_sha256=content_sha256(
                {"name": "loan-agent", "versions": LoanAgent.versions}
            ),
            invocation_config={"provider": "deterministic"},
        )
        runs = RunManagement(repository, DEFAULT_EVALUATOR_MANAGEMENT)
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
