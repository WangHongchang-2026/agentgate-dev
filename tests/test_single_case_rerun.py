import pytest

from agentgate.application.target_catalog import TargetCatalog
from agentgate.control_plane.service import EvaluationService
from agentgate.domain import RunStatus
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


def test_repeated_rerun_keeps_direct_parent_and_root(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "chain.db"))
    original = service.launch("loan-agent-v1-risky")
    case_id = original.snapshot.dataset.cases[0].id

    first = service.rerun_case(original.id, case_id)
    second = service.rerun_case(first.id, case_id, "loan-agent-v1-risky")

    assert first.snapshot.target.version == "loan-agent-v2-fixed"
    assert second.parent_run_id == first.id
    assert second.root_run_id == original.id


def test_target_catalog_marks_latest_explicitly_and_validates_versions():
    catalog = TargetCatalog()
    versions = catalog.versions()

    assert sum(item["is_latest"] for item in versions) == 1
    assert catalog.resolve(None) == "loan-agent-v2-fixed"
    assert catalog.resolve("loan-agent-v1-risky") == "loan-agent-v1-risky"
    with pytest.raises(ValueError, match="unknown target version"):
        catalog.resolve("missing")


def test_rerun_rejects_invalid_sources_without_creating_a_run(tmp_path):
    repository = SQLiteRepository(tmp_path / "invalid.db")
    service = EvaluationService(repository)
    original = service.launch("loan-agent-v1-risky")
    case_id = original.snapshot.dataset.cases[0].id
    count = len(repository.list_runs())

    with pytest.raises(LookupError, match="run not found"):
        service.rerun_case("missing", case_id)
    with pytest.raises(LookupError, match="case not found"):
        service.rerun_case(original.id, "missing")
    with pytest.raises(ValueError, match="unknown target version"):
        service.rerun_case(original.id, case_id, "missing")

    assert len(repository.list_runs()) == count


def test_comparison_rejects_normal_and_incomplete_runs(tmp_path):
    repository = SQLiteRepository(tmp_path / "comparison-errors.db")
    service = EvaluationService(repository)
    original = service.launch("loan-agent-v1-risky")
    with pytest.raises(ValueError, match="not a single-Case rerun"):
        service.rerun_comparison(original.id)

    case_id = original.snapshot.dataset.cases[0].id
    rerun = service.rerun_case(original.id, case_id)
    repository.save_run(rerun.model_copy(update={"status": RunStatus.RUNNING}))
    with pytest.raises(ValueError, match="rerun is not completed"):
        service.rerun_comparison(rerun.id)
