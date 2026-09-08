import sqlite3
from uuid import uuid4

import pytest

from agentgate.storage.sqlite import SQLiteRepository


def completed_run(tmp_path, execute_demo):
    repository = SQLiteRepository(tmp_path / "results.db")
    run, _ = execute_demo(repository, "loan-agent-v2-fixed")
    return repository, run, repository.list_results(run.id)


def test_results_are_immutable_idempotent_and_logically_unique(tmp_path, execute_demo):
    repository, run, results = completed_run(tmp_path, execute_demo)
    first = results[0]

    repository.save_results(results)
    changed = first.model_copy(update={"reason": "changed"})
    with pytest.raises(ValueError, match="EvaluationResult is immutable"):
        repository.save_results((changed,))

    duplicate = first.model_copy(update={"id": str(uuid4())})
    with pytest.raises(ValueError, match="already have an EvaluationResult"):
        repository.save_results((duplicate,))
    assert repository.list_results(run.id) == results


def test_result_batch_rejects_duplicate_ids_and_logical_keys(tmp_path, execute_demo):
    _, _, results = completed_run(tmp_path, execute_demo)
    first = results[0]

    with pytest.raises(ValueError, match="ids must be unique"):
        SQLiteRepository(tmp_path / "duplicate-id.db").save_results((first, first))
    duplicate_key = first.model_copy(update={"id": str(uuid4())})
    with pytest.raises(ValueError, match="unique by Run, Case, and Evaluator"):
        SQLiteRepository(tmp_path / "duplicate-key.db").save_results(
            (first, duplicate_key)
        )


def test_result_requires_existing_matching_run_and_trace(tmp_path, execute_demo):
    _, _, results = completed_run(tmp_path, execute_demo)
    result = results[0]
    empty = SQLiteRepository(tmp_path / "orphan.db")

    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        empty.save_results((result,))


def test_result_batch_rolls_back_when_a_later_result_conflicts(tmp_path, execute_demo):
    repository, run, results = completed_run(tmp_path, execute_demo)
    first, second = results[:2]
    with sqlite3.connect(repository.path) as connection:
        connection.execute("DELETE FROM results WHERE id = ?", (first.id,))

    conflict = second.model_copy(update={"id": str(uuid4())})
    with pytest.raises(ValueError, match="already have an EvaluationResult"):
        repository.save_results((first, conflict))

    stored = repository.list_results(run.id)
    assert first not in stored
    assert second in stored


def test_result_listing_is_deterministically_ordered(tmp_path, execute_demo):
    repository, run, results = completed_run(tmp_path, execute_demo)

    assert [result.evaluator_id for result in results] == sorted(
        result.evaluator_id for result in results
    )
    assert repository.list_results("unknown-run") == []
