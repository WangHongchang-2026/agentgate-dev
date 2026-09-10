from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentgate.dataset.formats.xlsx import dump as dump_xlsx
from agentgate.domain import Case, CaseDifficulty, CaseTurn
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes.datasets import router


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    app.state.dependencies = build_dependencies(tmp_path / "dataset-routes.db")
    app.include_router(router)
    return TestClient(app)


def test_dataset_routes_preserve_create_edit_publish_and_export(tmp_path) -> None:
    with _client(tmp_path) as client:
        created = client.post(
            "/api/datasets",
            json={"name": "Route Dataset", "description": "HTTP workflow"},
        )
        assert created.status_code == 201
        dataset_id = created.json()["dataset"]["id"]

        case = Case(
            id="route-case",
            name="Route Case",
            turns=(CaseTurn(id="route-turn", input={"message": "hello"}),),
        )
        saved = client.post(
            f"/api/datasets/{dataset_id}/drafts/cases",
            json=case.model_dump(mode="json"),
        )
        assert saved.status_code == 201
        assert saved.json()["cases"][0]["id"] == "route-case"

        published = client.post(f"/api/datasets/{dataset_id}/drafts/publish")
        assert published.status_code == 200
        assert published.json()["version"] == 1

        summary = next(
            item
            for item in client.get("/api/datasets").json()
            if item["id"] == dataset_id
        )
        assert summary["version"] == 1
        assert summary["case_count"] == 1
        assert summary["has_draft"] is False

        exported = client.get(
            f"/api/datasets/{dataset_id}/versions/1/export"
        )
        assert exported.status_code == 200
        assert exported.json()["format"] == "agentgate.dataset"


def test_xlsx_routes_import_draft_and_stream_published_version(tmp_path) -> None:
    content = dump_xlsx(
        [
            {
                "id": "xlsx-case",
                "name": "XLSX Case",
                "turns": [
                    {
                        "id": "xlsx-turn",
                        "input": {"message": "hello"},
                        "expectations": [],
                    }
                ],
            }
        ]
    )

    with _client(tmp_path) as client:
        imported = client.post(
            "/api/datasets/import/xlsx",
            data={"name": "Imported Workbook", "description": "XLSX route"},
            files={
                "file": (
                    "cases.xlsx",
                    content,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert imported.status_code == 201
        dataset_id = imported.json()["dataset"]["id"]
        assert imported.json()["version"]["cases"][0]["id"] == "xlsx-case"

        published = client.post(f"/api/datasets/{dataset_id}/drafts/publish")
        assert published.status_code == 200
        downloaded = client.get(
            f"/api/datasets/{dataset_id}/versions/1/export/xlsx"
        )

        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"PK")
        assert downloaded.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "Imported-Workbook-v1.xlsx" in downloaded.headers[
            "content-disposition"
        ]
        assert downloaded.headers["etag"] == f'"{published.json()["content_sha256"]}"'


def test_case_difficulty_and_notes_update_creates_traceable_dataset_version(
    tmp_path,
) -> None:
    with _client(tmp_path) as client:
        created = client.post(
            "/api/datasets",
            json={"name": "Regression Dataset", "description": "Case metadata"},
        )
        dataset_id = created.json()["dataset"]["id"]
        case = Case(
            id="metadata-case",
            name="Metadata Case",
            difficulty=CaseDifficulty.EASY,
            notes="Initial review note",
            turns=(CaseTurn(id="metadata-turn", input={"message": "hello"}),),
        )
        assert client.post(
            f"/api/datasets/{dataset_id}/drafts/cases",
            json=case.model_dump(mode="json"),
        ).status_code == 201
        assert client.post(
            f"/api/datasets/{dataset_id}/drafts/publish"
        ).status_code == 200

        assert client.post(
            f"/api/datasets/{dataset_id}/drafts",
            json={"based_on_version": 1},
        ).status_code == 201
        updated_case = case.model_copy(
            update={
                "difficulty": CaseDifficulty.HARD,
                "notes": "Confirmed difficult after regression review",
            }
        )
        updated = client.put(
            f"/api/datasets/{dataset_id}/drafts/cases/{case.id}",
            json=updated_case.model_dump(mode="json"),
        )

        assert updated.status_code == 200
        assert updated.json()["cases"][0]["difficulty"] == "hard"
        assert updated.json()["cases"][0]["notes"] == (
            "Confirmed difficult after regression review"
        )
        assert client.post(
            f"/api/datasets/{dataset_id}/drafts/publish"
        ).status_code == 200

        first = client.get(f"/api/datasets/{dataset_id}/versions/1").json()
        second = client.get(f"/api/datasets/{dataset_id}/versions/2").json()
        assert first["cases"][0]["difficulty"] == "easy"
        assert first["cases"][0]["notes"] == "Initial review note"
        assert second["cases"][0]["difficulty"] == "hard"
        assert second["cases"][0]["notes"] == (
            "Confirmed difficult after regression review"
        )


def test_xlsx_route_returns_structured_validation_issues(tmp_path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/datasets/import/xlsx",
            data={"name": "Invalid"},
            files={"file": ("invalid.xlsx", b"not a workbook")},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "xlsx_validation_failed",
        "issue_count": 1,
        "issues": [
            {
                "sheet": "Cases",
                "row": None,
                "column": None,
                "message": "file is not a valid XLSX archive",
            }
        ],
    }


def test_dataset_routes_require_configured_dependencies() -> None:
    app = FastAPI()
    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/datasets")

    assert response.status_code == 500
