from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agentgate.case import DatasetExport, DatasetValidationError
from agentgate.control_plane import EvaluationService
from agentgate.domain import Case, DatasetPurpose
from agentgate.storage.sqlite import SQLiteRepository
from agentgate.trace.receivers.otlp_http import ingest_otlp_http_json


class LaunchRequest(BaseModel):
    version: str
    dataset_id: str
    dataset_version: int = Field(ge=1)
    evaluator_ids: list[str] | None = None


class RerunCaseRequest(BaseModel):
    target_version: str | None = None


class CreateDatasetRequest(BaseModel):
    name: str
    description: str = ""
    purpose: DatasetPurpose = DatasetPurpose.STANDARD


class AddRegressionCaseRequest(BaseModel):
    regression_dataset_id: str | None = None
    new_dataset_name: str | None = None
    new_dataset_description: str = ""
    reason: str = ""


class UpdateDatasetRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    archived: bool | None = None


class CopyDatasetRequest(BaseModel):
    name: str
    source_version: int | None = None


class CreateDraftRequest(BaseModel):
    based_on_version: int | None = None


class ReorderCasesRequest(BaseModel):
    case_ids: list[str]


def _raise_dataset_error(exc: ValueError, status_code: int = 422) -> None:
    detail: Any = str(exc)
    if isinstance(exc, DatasetValidationError):
        detail = [item.model_dump(mode="json") for item in exc.issues]
    raise HTTPException(status_code=status_code, detail=detail) from exc


def create_app(database_path: str | Path | None = None) -> FastAPI:
    repository = SQLiteRepository(database_path or os.getenv("AGENTGATE_DB", "agentgate.db"))
    service = EvaluationService(repository)
    datasets = service.dataset_service
    app = FastAPI(title="AgentGate", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api = APIRouter(prefix="/api")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/overview")
    def overview():
        return service.overview()

    @api.get("/versions")
    def versions():
        return service.versions()

    @api.get("/datasets")
    def list_datasets():
        return service.datasets()

    @api.post("/datasets", status_code=201)
    def create_dataset(request: CreateDatasetRequest):
        try:
            dataset = datasets.create_dataset(
                request.name, request.description, request.purpose,
            )
            draft = datasets.create_draft(dataset.id)
            return {"dataset": dataset, "draft": draft}
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.get("/datasets/{dataset_id}")
    def dataset_detail(dataset_id: str):
        try:
            return {
                "dataset": datasets.get_dataset(dataset_id),
                "versions": datasets.list_versions(dataset_id),
            }
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.patch("/datasets/{dataset_id}")
    def update_dataset(dataset_id: str, request: UpdateDatasetRequest):
        try:
            return datasets.update_dataset(
                dataset_id,
                name=request.name,
                description=request.description,
                archived=request.archived,
            )
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.delete("/datasets/{dataset_id}")
    def archive_dataset(dataset_id: str):
        try:
            return datasets.archive_dataset(dataset_id)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.post("/datasets/{dataset_id}/copy", status_code=201)
    def copy_dataset(dataset_id: str, request: CopyDatasetRequest):
        try:
            dataset, draft = datasets.copy_dataset(
                dataset_id, request.name, request.source_version
            )
            return {"dataset": dataset, "draft": draft}
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.get("/datasets/{dataset_id}/versions")
    def list_dataset_versions(dataset_id: str):
        try:
            return datasets.list_versions(dataset_id)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.get("/datasets/{dataset_id}/versions/{version}")
    def dataset_version(dataset_id: str, version: int):
        try:
            return datasets.get_version(dataset_id, version)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.get("/datasets/{dataset_id}/drafts/current")
    def current_draft(dataset_id: str):
        try:
            draft = datasets.get_draft(dataset_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="dataset has no active draft")
            return draft
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.post("/datasets/{dataset_id}/drafts", status_code=201)
    def create_draft(dataset_id: str, request: CreateDraftRequest):
        try:
            return datasets.create_draft(dataset_id, request.based_on_version)
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.delete("/datasets/{dataset_id}/drafts/current", status_code=204)
    def discard_draft(dataset_id: str):
        try:
            datasets.discard_draft(dataset_id)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.post("/datasets/{dataset_id}/drafts/publish")
    def publish_draft(dataset_id: str):
        try:
            return datasets.publish_draft(dataset_id)
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.post("/datasets/{dataset_id}/drafts/cases", status_code=201)
    def add_case(dataset_id: str, case: Case):
        try:
            return datasets.save_case(dataset_id, case)
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.put("/datasets/{dataset_id}/drafts/cases/{case_id}")
    def update_case(dataset_id: str, case_id: str, case: Case):
        if case.id != case_id:
            raise HTTPException(status_code=422, detail="Case ID cannot be changed")
        try:
            return datasets.save_case(dataset_id, case)
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.delete("/datasets/{dataset_id}/drafts/cases/{case_id}")
    def delete_case(dataset_id: str, case_id: str):
        try:
            return datasets.remove_case(dataset_id, case_id)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.post("/datasets/{dataset_id}/drafts/cases/{case_id}/copy")
    def copy_case(dataset_id: str, case_id: str):
        try:
            return datasets.copy_case(dataset_id, case_id)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.put("/datasets/{dataset_id}/drafts/case-order")
    def reorder_cases(dataset_id: str, request: ReorderCasesRequest):
        try:
            return datasets.reorder_cases(dataset_id, request.case_ids)
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.get("/datasets/{dataset_id}/versions/{version}/export")
    def export_dataset(dataset_id: str, version: int):
        try:
            return datasets.export_version(dataset_id, version)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.post("/datasets/import", status_code=201)
    def import_dataset(payload: DatasetExport):
        try:
            dataset, version = datasets.import_dataset(payload.model_dump(mode="json"))
            return {"dataset": dataset, "version": version}
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.get("/evaluators")
    def evaluators():
        return service.evaluators()

    @api.get("/runs")
    def runs():
        return repository.list_runs()

    @api.post("/evaluations", status_code=201)
    def launch(request: LaunchRequest):
        try:
            return service.launch(
                request.version,
                request.dataset_id,
                request.dataset_version,
                request.evaluator_ids,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/runs/{run_id}")
    def run_detail(run_id: str):
        report = service.run_detail(run_id)
        if report is None:
            raise HTTPException(status_code=404, detail="run not found")
        return report

    @api.post("/runs/{run_id}/cases/{case_id}/rerun", status_code=201)
    def rerun_case(run_id: str, case_id: str, request: RerunCaseRequest):
        try:
            return service.rerun_case(run_id, case_id, request.target_version)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/runs/{run_id}/comparison")
    def rerun_comparison(run_id: str):
        try:
            return service.rerun_comparison(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.post("/runs/{run_id}/cases/{case_id}/regression", status_code=201)
    def add_case_to_regression_dataset(
        run_id: str, case_id: str, request: AddRegressionCaseRequest,
    ):
        try:
            dataset, draft, copied = service.add_case_to_regression_dataset(
                run_id=run_id,
                case_id=case_id,
                regression_dataset_id=request.regression_dataset_id,
                new_dataset_name=request.new_dataset_name,
                new_dataset_description=request.new_dataset_description,
                reason=request.reason,
            )
            return {"dataset": dataset, "draft": draft, "case": copied}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.get("/runs/{run_id}/traces/{case_id}")
    def trace_detail(run_id: str, case_id: str):
        trace = service.trace(run_id, case_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return trace

    @app.post("/v1/traces", status_code=202)
    async def receive_otlp(request: Request):
        content_type = request.headers.get("content-type", "")
        if "json" not in content_type:
            raise HTTPException(status_code=415, detail="P1 receiver accepts OTLP/HTTP JSON")
        try:
            count = ingest_otlp_http_json(await request.json(), repository)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"accepted_spans": count}

    app.include_router(api)
    app.state.repository = repository
    app.state.service = service
    return app


app = create_app()
