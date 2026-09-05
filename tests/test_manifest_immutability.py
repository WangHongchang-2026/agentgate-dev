import json
import sqlite3

import pytest

from agentgate.domain import (
    Case, CaseTurn, ReleaseGateSpec, MetricPlan, EvaluationRun, RunManifest, TargetRef,
    TargetSnapshot, TargetType,
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
