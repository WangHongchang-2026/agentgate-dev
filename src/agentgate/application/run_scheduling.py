"""Application workflow for releasing due Evaluation Runs."""

from __future__ import annotations

from datetime import datetime

from agentgate.domain import EvaluationRun, RunStatus, transition_run, utcnow
from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.storage.repository import AgentGateRepository


class RunScheduling:
    """Move due scheduled Runs into the asynchronous execution queue."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def dispatch_due_runs(
        self,
        dispatcher: JobDispatcher,
        *,
        now: datetime | None = None,
        limit: int = 100,
    ) -> tuple[EvaluationRun, ...]:
        release_time = now or utcnow()
        due_runs = self.repository.claim_due_scheduled_runs(
            release_time,
            limit=limit,
        )
        dispatched: list[EvaluationRun] = []
        for run in due_runs:
            try:
                dispatcher.submit(run.id)
            except Exception as exc:
                failed = transition_run(
                    run,
                    RunStatus.FAILED,
                    occurred_at=release_time,
                    error=f"Run dispatch failed: {type(exc).__name__}",
                )
                self.repository.save_run(failed)
                continue
            dispatched.append(run)
        return tuple(dispatched)
