import json
import sqlite3
from datetime import timedelta

import pytest

from agentgate.domain import (
    Case, CaseTurn, ReleaseGateSpec, MetricPlan, EvaluationRun, RunManifest, TargetRef,
    RunStatus, TargetSnapshot, TargetType, transition_run,
)
from agentgate.demo.loan import LOAN_DATASET_VERSION
from agentgate.evaluator import EVALUATORS
from agentgate.storage.sqlite import SQLiteRepository


def manifest():
    return RunManifest(
        dataset=LOAN_DATASET_VERSION,
        target=TargetSnapshot(
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
        evaluator_specs=EVALUATORS,
        primary_evaluator_ids=tuple(item.id for item in EVALUATORS),
        metric_plan=MetricPlan(),
        gate_spec=ReleaseGateSpec(),
    )


def test_manifest_is_deeply_immutable_and_hash_is_stable():
    first = manifest()
    second = RunManifest.model_validate(first.model_dump(mode="json"))
    assert first.manifest_sha256 == second.manifest_sha256
    with pytest.raises(TypeError):
        first.dataset.cases[0].turns[0].input["risk"] = "low"


def test_mutating_source_data_cannot_change_domain_content():
    source = {"nested": [{"risk": "high"}]}
    case = Case(
        id="case", name="case",
        turns=(CaseTurn(id="turn", input=source),),
    )
    source["nested"][0]["risk"] = "low"
    assert case.turns[0].input["nested"][0]["risk"] == "high"


def test_repository_rejects_tampered_manifest(tmp_path):
    repository = SQLiteRepository(tmp_path / "tamper.db")
    run = EvaluationRun(manifest=manifest())
    repository.save_run(run)
    with sqlite3.connect(repository.path) as db:
        payload = json.loads(db.execute(
            "SELECT payload FROM runs WHERE id=?", (run.id,)
        ).fetchone()[0])
        payload["manifest"]["target"]["ref"]["external_version_id"] = "tampered"
        db.execute("UPDATE runs SET payload=? WHERE id=?", (json.dumps(payload), run.id))
    with pytest.raises(ValueError, match="hash mismatch"):
        repository.get_run(run.id)


def test_repository_preserves_run_identity_and_terminal_state(tmp_path):
    repository = SQLiteRepository(tmp_path / "run-lifecycle.db")
    pending = EvaluationRun(id="run", manifest=manifest())
    repository.save_run(pending)

    changed_creation = pending.model_copy(
        update={"created_at": pending.created_at + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="created_at is immutable"):
        repository.save_run(changed_creation)

    changed_manifest = pending.model_copy(
        update={"manifest": manifest().model_copy(update={"created_at": pending.created_at})}
    )
    with pytest.raises(ValueError, match="manifest is immutable"):
        repository.save_run(changed_manifest)

    running = transition_run(
        pending, RunStatus.RUNNING, occurred_at=pending.created_at + timedelta(seconds=1)
    )
    repository.save_run(running)
    changed_start = running.model_copy(
        update={"started_at": running.started_at + timedelta(seconds=1)}
    )
    with pytest.raises(ValueError, match="started_at is immutable"):
        repository.save_run(changed_start)

    completed = transition_run(
        running, RunStatus.COMPLETED, occurred_at=running.started_at + timedelta(seconds=1)
    )
    repository.save_run(completed)
    repository.save_run(completed)
    with pytest.raises(ValueError, match="terminal EvaluationRun is immutable"):
        repository.save_run(running)
    assert repository.get_run(pending.id) == completed


def test_repository_lists_runs_with_valid_limit_and_deterministic_ties(tmp_path):
    repository = SQLiteRepository(tmp_path / "run-list.db")
    first = EvaluationRun(id="b-run", manifest=manifest())
    second = EvaluationRun(id="a-run", manifest=manifest(), created_at=first.created_at)
    repository.save_run(first)
    repository.save_run(second)

    assert [run.id for run in repository.list_runs()] == ["a-run", "b-run"]
    assert [run.id for run in repository.list_runs(limit=1)] == ["a-run"]
    with pytest.raises(ValueError, match="limit must be at least 1"):
        repository.list_runs(limit=0)
