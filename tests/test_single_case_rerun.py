from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from agentgate.control_plane.service import (
    EvaluationService,
    _comparison_status,
    _overall_comparison,
)
from agentgate.server.application import create_app
from agentgate.storage.sqlite import SQLiteRepository


def test_single_case_rerun_reuses_snapshot_and_records_lineage(tmp_path):
    repository = SQLiteRepository(tmp_path / "rerun.db")
    service = EvaluationService(repository)
    original = service.launch("loan-agent-v1-risky")
    original_report = service.run_detail(original.id)
    case = original.snapshot.dataset.cases[0]

    rerun = service.rerun_case(original.id, case.id, "loan-agent-v2-fixed")

    assert rerun.snapshot.dataset == original.snapshot.dataset
    assert rerun.snapshot.selected_case_ids == (case.id,)
    assert rerun.snapshot.evaluator_specs == original.snapshot.evaluator_specs
    assert rerun.snapshot.metric_plan == original.snapshot.metric_plan
    assert rerun.snapshot.gate_spec == original.snapshot.gate_spec
    assert rerun.parent_run_id == original.id
    assert rerun.root_run_id == original.id
    assert rerun.rerun_case_id == case.id
    assert len(repository.list_traces(rerun.id)) == 1
    assert {item.case_id for item in repository.list_results(rerun.id)} == {case.id}
    assert service.run_detail(original.id) == original_report

    comparison = service.rerun_comparison(rerun.id)
    assert comparison["before_target_version"] == "loan-agent-v1-risky"
    assert comparison["after_target_version"] == "loan-agent-v2-fixed"
    assert comparison["overall"] == "improved"
    assert comparison["counts"]["improved"] > 0


def test_repeated_single_case_rerun_keeps_direct_parent_and_root(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "rerun-chain.db"))
    original = service.launch("loan-agent-v1-risky")
    case_id = original.snapshot.dataset.cases[0].id
    first = service.rerun_case(original.id, case_id)
    second = service.rerun_case(first.id, case_id, "loan-agent-v1-risky")

    assert first.snapshot.target.version == service.latest_target_version()
    assert second.parent_run_id == first.id
    assert second.root_run_id == original.id


def test_single_case_rerun_api_and_errors(tmp_path):
    with TestClient(create_app(tmp_path / "rerun-api.db")) as client:
        launched = client.post("/api/evaluations", json={
            "version": "loan-agent-v1-risky",
            "dataset_id": "loan-risk-policy",
            "dataset_version": 1,
        }).json()
        case_id = launched["snapshot"]["dataset"]["cases"][0]["id"]

        response = client.post(
            f"/api/runs/{launched['id']}/cases/{case_id}/rerun",
            json={"target_version": "loan-agent-v2-fixed"},
        )
        assert response.status_code == 201
        rerun = response.json()
        assert rerun["snapshot"]["selected_case_ids"] == [case_id]
        comparison = client.get(f"/api/runs/{rerun['id']}/comparison")
        assert comparison.status_code == 200
        assert comparison.json()["parent_run_id"] == launched["id"]

        assert client.post(
            f"/api/runs/missing/cases/{case_id}/rerun", json={}
        ).status_code == 404
        assert client.post(
            f"/api/runs/{launched['id']}/cases/missing/rerun", json={}
        ).status_code == 404
        assert client.post(
            f"/api/runs/{launched['id']}/cases/{case_id}/rerun",
            json={"target_version": "missing"},
        ).status_code == 422
        assert client.get(f"/api/runs/{launched['id']}/comparison").status_code == 422


def test_versions_identify_latest_explicitly(tmp_path):
    with TestClient(create_app(tmp_path / "versions.db")) as client:
        versions = client.get("/api/versions").json()
    assert sum(item["is_latest"] for item in versions) == 1
    assert next(item["id"] for item in versions if item["is_latest"]) == "loan-agent-v2-fixed"


@pytest.mark.parametrize(("before", "after", "expected"), [
    (("fail", 0.0), ("pass", 1.0), "improved"),
    (("pass", 1.0), ("review", 0.5), "regressed"),
    (("pass", 0.5), ("pass", 0.75), "improved"),
    (("pass", 0.75), ("pass", 0.5), "regressed"),
    (("pass", 1.0), ("pass", 1.0), "unchanged"),
    (("error", None), ("pass", 1.0), "incomparable"),
    (("pass", 1.0), ("not_applicable", None), "incomparable"),
])
def test_evaluator_comparison_truth_table(before, after, expected):
    assert _comparison_status(
        SimpleNamespace(outcome=before[0], score=before[1]),
        SimpleNamespace(outcome=after[0], score=after[1]),
    ) == expected


@pytest.mark.parametrize(("counts", "total", "expected"), [
    ({"improved": 1, "regressed": 1, "unchanged": 0, "incomparable": 0}, 2, "mixed"),
    ({"improved": 0, "regressed": 1, "unchanged": 2, "incomparable": 0}, 3, "regressed"),
    ({"improved": 1, "regressed": 0, "unchanged": 2, "incomparable": 0}, 3, "improved"),
    ({"improved": 0, "regressed": 0, "unchanged": 2, "incomparable": 0}, 2, "unchanged"),
    ({"improved": 0, "regressed": 0, "unchanged": 0, "incomparable": 2}, 2, "incomparable"),
])
def test_overall_comparison_truth_table(counts, total, expected):
    assert _overall_comparison(counts, total) == expected
