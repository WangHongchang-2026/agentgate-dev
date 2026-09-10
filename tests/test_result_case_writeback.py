import pytest

from agentgate.application import DatasetManagement
from agentgate.application.result_case_writeback import (
    HistoricalCaseNotFound,
    HistoricalRunNotFound,
    ResultCaseIdentityMismatch,
    ResultCaseNotFailed,
    ResultCaseWriteback,
)
from agentgate.domain import Case, CaseDifficulty, CaseTurn, Outcome
from agentgate.storage.sqlite import SQLiteRepository


def workflow(repository: SQLiteRepository) -> ResultCaseWriteback:
    return ResultCaseWriteback(
        repository,
        DatasetManagement(repository),
    )


def test_get_historical_case_returns_exact_executed_snapshot(
    tmp_path, execute_demo
) -> None:
    repository = SQLiteRepository(tmp_path / "historical-case.db")
    run, report = execute_demo(repository, "loan-agent-v1-risky")

    historical = workflow(repository).get_historical_case(
        run.id, "high-risk-approval"
    )

    assert historical.run_id == run.id
    assert historical.dataset_id == run.manifest.dataset.dataset_id
    assert historical.dataset_version == run.manifest.dataset.version
    assert historical.case == run.manifest.execution_cases[0]
    assert historical.results == tuple(report.results)
    assert any(result.outcome is Outcome.FAIL for result in historical.results)


def test_writeback_bases_new_draft_on_latest_publication(
    tmp_path, execute_demo
) -> None:
    repository = SQLiteRepository(tmp_path / "latest-writeback.db")
    run, _ = execute_demo(repository, "loan-agent-v1-risky")
    datasets = DatasetManagement(repository)
    dataset_id = run.manifest.dataset.dataset_id
    source_case = run.manifest.execution_cases[0]
    sibling = Case(
        id="later-case",
        name="Added after the failed Run",
        turns=(CaseTurn(id="later-turn", input={"message": "later"}),),
    )
    datasets.create_draft(dataset_id, based_on_version=1)
    datasets.save_case(dataset_id, sibling)
    second = datasets.publish_draft(dataset_id)
    edited = source_case.model_copy(
        update={
            "difficulty": CaseDifficulty.EASY,
            "notes": "Clarified after reviewing the failed result.",
        }
    )

    written = workflow(repository).write_to_draft(
        run.id, source_case.id, edited
    )

    assert written.source_dataset_version == 1
    assert written.draft.based_on_version == second.version == 2
    assert {item.id for item in written.draft.cases} == {
        source_case.id,
        sibling.id,
    }
    assert next(
        item for item in written.draft.cases if item.id == source_case.id
    ) == edited
    assert datasets.get_version(dataset_id, 1).cases[0] == source_case
    assert next(
        item for item in datasets.get_version(dataset_id, 2).cases
        if item.id == source_case.id
    ) == source_case


def test_writeback_reuses_active_draft_and_preserves_other_cases(
    tmp_path, execute_demo
) -> None:
    repository = SQLiteRepository(tmp_path / "existing-draft.db")
    run, _ = execute_demo(repository, "loan-agent-v1-risky")
    datasets = DatasetManagement(repository)
    dataset_id = run.manifest.dataset.dataset_id
    source_case = run.manifest.execution_cases[0]
    existing = datasets.create_draft(dataset_id, based_on_version=1)
    sibling = Case(
        id="draft-only-case",
        name="Draft-only Case",
        turns=(CaseTurn(id="draft-turn", input={"message": "draft"}),),
    )
    datasets.save_case(dataset_id, sibling)
    edited = source_case.model_copy(update={"notes": "Reviewed failure."})

    written = workflow(repository).write_to_draft(
        run.id, source_case.id, edited
    )

    assert written.draft.id == existing.id
    assert {item.id for item in written.draft.cases} == {
        source_case.id,
        sibling.id,
    }
    assert next(
        item for item in written.draft.cases if item.id == source_case.id
    ).notes == "Reviewed failure."


def test_writeback_rejects_unknown_nonfailed_and_changed_identity(
    tmp_path, execute_demo
) -> None:
    repository = SQLiteRepository(tmp_path / "writeback-errors.db")
    risky, _ = execute_demo(repository, "loan-agent-v1-risky")
    fixed, _ = execute_demo(repository, "loan-agent-v2-fixed")
    application = workflow(repository)

    with pytest.raises(HistoricalRunNotFound, match="unknown EvaluationRun"):
        application.get_historical_case("missing", "case")
    with pytest.raises(HistoricalCaseNotFound, match="did not execute Case"):
        application.get_historical_case(risky.id, "missing")
    with pytest.raises(ResultCaseNotFailed, match="no failed Result"):
        application.write_to_draft(
            fixed.id,
            fixed.manifest.execution_cases[0].id,
            fixed.manifest.execution_cases[0],
        )
    with pytest.raises(ResultCaseIdentityMismatch, match="id must match"):
        application.write_to_draft(
            risky.id,
            risky.manifest.execution_cases[0].id,
            risky.manifest.execution_cases[0].model_copy(update={"id": "changed"}),
        )
