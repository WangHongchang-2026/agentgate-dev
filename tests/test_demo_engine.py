from agentgate.control_plane import EvaluationService
from agentgate.storage.sqlite import SQLiteRepository


def test_risky_fails_and_fixed_improves(tmp_path):
    repository = SQLiteRepository(tmp_path / "demo.db")
    service = EvaluationService(repository)
    risky = service.launch("loan-agent-v1-risky")
    fixed = service.launch("loan-agent-v2-fixed")
    risky_report = service.run_detail(risky.id)
    fixed_report = service.run_detail(fixed.id)
    assert risky_report.release_gate.outcome == "fail"
    assert risky_report.metrics[0].failed >= 3
    assert fixed_report.release_gate.outcome == "pass"
    assert fixed_report.release_gate.score > risky_report.release_gate.score
    assert len(repository.list_traces(risky.id)) == 1
    assert len(repository.list_results(fixed.id)) == 7
    failures = [result for result in risky_report.results if result.outcome == "fail"]
    assert all(result.primary_failure_stage for result in failures)
    assert service.loan_state["A-100"]["status"] == "pending_review"
