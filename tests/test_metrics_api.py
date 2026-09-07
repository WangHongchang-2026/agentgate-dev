from fastapi.testclient import TestClient

from agentgate.integrations.job_dispatchers.celery import execute_evaluation_run
from agentgate.server.app import create_app


class RecordingDispatcher:
    def __init__(self) -> None:
        self.run_ids: list[str] = []

    def submit(self, run_id: str) -> None:
        self.run_ids.append(run_id)


def test_config_catalogs_and_real_report_metrics(tmp_path, monkeypatch):
    database_path = tmp_path / "metrics.db"
    dispatcher = RecordingDispatcher()
    monkeypatch.setenv("AGENTGATE_DB", str(database_path))
    with TestClient(create_app(database_path, dispatcher)) as client:
        datasets = client.get("/api/datasets").json()
        evaluators = client.get("/api/evaluators").json()
        assert len(datasets) == 1
        assert datasets[0]["id"] == "loan-risk-policy"
        assert datasets[0]["version"] == 1
        assert datasets[0]["case_count"] == 1
        assert datasets[0]["has_draft"] is False
        assert len(evaluators) == 7
        assert {item["kind"] for item in evaluators} == {"rule"}
        assert {item["dimension"] for item in evaluators} == {
            "routing", "tool_use", "state", "answer", "safety",
        }

        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v1-risky", "dataset_id": "loan-risk-policy",
            "dataset_version": 1,
            "evaluator_ids": ["required-tool", "forbidden-tool", "tool-arguments"],
        })
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        assert dispatcher.run_ids == [run_id]
        assert execute_evaluation_run.run(run_id) == "completed"
        report = client.get(f"/api/runs/{run_id}").json()
        assert len(report["results"]) == 3
        metrics = {(item["level"], item["key"]): item for item in report["metrics"]}
        assert metrics[("dimension", "tool_use")]["key"] == "tool_use"
        assert "label" not in metrics[("dimension", "tool_use")]
        assert metrics[("dimension", "tool_use")]["score"] == 0.25
        assert metrics[("overall", "overall")]["score"] == 0.25


def test_launch_rejects_empty_evaluator_selection(tmp_path):
    with TestClient(create_app(tmp_path / "invalid.db")) as client:
        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v2-fixed",
            "dataset_id": "loan-risk-policy",
            "dataset_version": 1,
            "evaluator_ids": [],
        })
        assert response.status_code == 422
