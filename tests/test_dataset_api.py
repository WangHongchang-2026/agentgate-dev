from fastapi.testclient import TestClient

from agentgate.domain import (
    Case, CaseCategory, CaseDifficulty, CaseTurn, Equals, OutputExpectation,
    PolicyExpectation, SkillRouteExpectation, StateExpectation, ToolCallExpectation,
)
from agentgate.server.application import create_app


def test_web_dataset_workflow_persists_and_runs_selected_version(tmp_path):
    with TestClient(create_app(tmp_path / "dataset-api.db")) as client:
        created = client.post("/api/datasets", json={
            "name": "UI Dataset", "description": "created from browser",
        })
        assert created.status_code == 201
        dataset_id = created.json()["dataset"]["id"]

        case = Case(
            id="ui-high-risk",
            name="UI high risk",
            category=CaseCategory.BOUNDARY,
            difficulty=CaseDifficulty.HARD,
            turns=(CaseTurn(
                id="ui-turn",
                input={
                    "skill": "loan_approval", "application_id": "UI-1",
                    "risk": "high", "amount": 80000,
                },
                expectations=(
                    SkillRouteExpectation(
                        id="route", condition=Equals(expected="loan_approval")
                    ),
                    StateExpectation(
                        id="status", path="status",
                        condition=Equals(expected="pending_review"),
                    ),
                    OutputExpectation(
                        id="output-status", path="status",
                        condition=Equals(expected="pending_review"),
                    ),
                    ToolCallExpectation(id="credit", tool="credit_inquiry"),
                    ToolCallExpectation(id="review", tool="request_human_review"),
                    ToolCallExpectation(
                        id="no-approval", tool="approve_loan", mode="forbidden"
                    ),
                    PolicyExpectation(
                        id="policy", policy_id="high_risk_requires_review"
                    ),
                ),
            ),),
        )
        saved = client.post(
            f"/api/datasets/{dataset_id}/drafts/cases",
            json=case.model_dump(mode="json"),
        )
        assert saved.status_code == 201
        published = client.post(f"/api/datasets/{dataset_id}/drafts/publish")
        assert published.status_code == 200
        assert published.json()["version"] == 1

        response = client.post("/api/evaluations", json={
            "version": "loan-agent-v2-fixed",
            "dataset_id": dataset_id,
            "dataset_version": 1,
        })
        assert response.status_code == 201
        report = client.get(f"/api/runs/{response.json()['id']}").json()
        assert report["run"]["manifest"]["dataset"]["dataset_id"] == dataset_id
        assert report["run"]["manifest"]["dataset"]["version"] == 1
        output = next(item for item in report["results"] if item["evaluator_id"] == "final-output")
        assert output["outcome"] == "pass"
        assert output["checks"][0]["expected"]["expected"] == "pending_review"
        assert output["checks"][0]["actual"] == "pending_review"


def test_publish_returns_domain_validation_message(tmp_path):
    with TestClient(create_app(tmp_path / "validation-api.db")) as client:
        created = client.post("/api/datasets", json={"name": "Empty"}).json()
        dataset_id = created["dataset"]["id"]
        response = client.post(f"/api/datasets/{dataset_id}/drafts/publish")
        assert response.status_code == 422
        assert "requires at least one Case" in response.json()["detail"]
