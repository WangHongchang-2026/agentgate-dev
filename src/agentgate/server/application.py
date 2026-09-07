from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import (
    APIRouter, FastAPI, File, Form, HTTPException, Request, Response, UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from agentgate.case import (
    DatasetExcelExportError,
    DatasetExcelValidationError,
    DatasetExport,
    DatasetValidationError,
    ExcelImportIssue,
)
from agentgate.application.dataset_generation import DatasetGenerationService
from agentgate.application.target_catalog import build_fake_target_catalog
from agentgate.case.generation.protocol import GenerationModel
from agentgate.control_plane import EvaluationService
from agentgate.domain import Case, DatasetPurpose, TargetRef, TargetType
from agentgate.run.targets.base import TargetIntegrationError
from agentgate.storage.sqlite import SQLiteRepository
from agentgate.integrations.model_providers import (
    OpenAICompatibleGenerationModel,
    RuntimeCredentialStore,
    bailian_default_profile,
)
from agentgate.server.dataset_generation_api import create_dataset_generation_router
from agentgate.trace.receivers.otlp_http import (
    decode_content_encoding, encode_otlp_http_protobuf_response,
    ingest_otlp_http_json, ingest_otlp_http_protobuf,
)
from agentgate.trace.models import OtlpIngestionLimits


class LaunchRequest(BaseModel):
    version: str
    dataset_id: str
    dataset_version: int = Field(ge=1)
    evaluator_ids: list[str] | None = None


class LaunchHttpRequest(BaseModel):
    endpoint: str
    target_id: str
    version_id: str
    credential_ref: str = ""
    platform_id: str = "external"
    dataset_id: str = "loan-risk-policy"
    dataset_version: int = Field(default=1, ge=1)
    evaluator_ids: list[str] | None = None
    timeout_seconds: float = Field(default=30.0, gt=0)


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


class ValidateSchemaRequest(BaseModel):
    json_schema: object | str
    instance_mode: Literal["structured", "json_text"] = "structured"


EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_EXCEL_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXCEL_REQUEST_BYTES = 11 * 1024 * 1024


class ExcelRequestBodyLimitMiddleware:
    """Bound the complete multipart envelope before FastAPI parses form data."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/datasets/import/excel"
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", ()))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > self.max_bytes:
                await self._reject(scope, receive, send)
                return

        messages: list[dict[str, Any]] = []
        received_size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                break
            if message["type"] != "http.request":
                continue
            received_size += len(message.get("body", b""))
            if received_size > self.max_bytes:
                await self._reject(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        message_index = 0

        async def replay_receive() -> dict[str, Any]:
            nonlocal message_index
            if message_index < len(messages):
                message = messages[message_index]
                message_index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _reject(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        issue = _excel_issue_detail(
            f"multipart request body exceeds {self.max_bytes // (1024 * 1024)} MiB"
        )
        response = JSONResponse(
            status_code=413,
            content={"detail": _excel_error_detail(
                "excel_import_validation_failed", [issue], 1, False
            )},
        )
        await response(scope, receive, send)


def _raise_dataset_error(exc: ValueError, status_code: int = 422) -> None:
    detail: Any = str(exc)
    if isinstance(exc, DatasetExcelValidationError):
        issues = [
            {
                "sheet": item.sheet,
                "row": item.row,
                "column": item.column,
                "message": item.message,
            }
            for item in exc.issues
        ]
        detail = _excel_error_detail(
            "excel_import_validation_failed",
            issues,
            exc.total_count,
            exc.truncated,
        )
    elif isinstance(exc, DatasetExcelExportError):
        issues = [
            {
                "sheet": item.sheet,
                "row": item.row,
                "column": item.column,
                "message": item.message,
            }
            for item in exc.issues
        ]
        detail = _excel_error_detail(
            "excel_export_validation_failed", issues, len(issues), False
        )
    elif isinstance(exc, DatasetValidationError):
        detail = [item.model_dump(mode="json") for item in exc.issues]
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _excel_issue_detail(message: str) -> dict[str, Any]:
    return {"sheet": "Cases", "row": None, "column": None, "message": message}


def _excel_error_detail(
    code: str,
    issues: list[dict[str, Any]],
    total_count: int,
    truncated: bool,
) -> dict[str, Any]:
    return {
        "code": code,
        "total_count": total_count,
        "truncated": truncated,
        "issues": issues,
    }


def _excel_upload_error(message: str) -> DatasetExcelValidationError:
    return DatasetExcelValidationError((ExcelImportIssue(
        sheet="Cases", row=None, column=None, message=message
    ),))


def _excel_attachment_filename(name: str, version: int) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return f"{sanitized or 'dataset'}-v{version}.xlsx"


def _excel_content_disposition(name: str, version: int) -> str:
    fallback = _excel_attachment_filename(name, version)
    utf8_name = quote(f"{name}-v{version}.xlsx", safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{utf8_name}'


def create_app(
    database_path: str | Path | None = None,
    generation_model: GenerationModel | None = None,
    generation_credential_store: RuntimeCredentialStore | None = None,
) -> FastAPI:
    repository = SQLiteRepository(database_path or os.getenv("AGENTGATE_DB", "agentgate.db"))
    service = EvaluationService(repository)
    datasets = service.dataset_service
    target_catalog = build_fake_target_catalog()
    credential_store = generation_credential_store or RuntimeCredentialStore()
    active_generation_model = generation_model or OpenAICompatibleGenerationModel(
        credential_lookup=credential_store.get
    )
    generation = DatasetGenerationService(
        datasets=datasets,
        targets=target_catalog,
        model=active_generation_model,
        profiles=(bailian_default_profile(),),
        acceptance_secret=repository.get_or_create_service_secret(
            "dataset_generation_acceptance_hmac"
        ),
    )
    app = FastAPI(title="AgentGate", version="0.1.0")
    app.add_middleware(
        ExcelRequestBodyLimitMiddleware,
        max_bytes=MAX_EXCEL_REQUEST_BYTES,
    )
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

    @api.get("/datasets/excel/template")
    def download_excel_template():
        return StreamingResponse(
            BytesIO(datasets.excel_template()),
            media_type=EXCEL_MEDIA_TYPE,
            headers={
                "Content-Disposition": 'attachment; filename="agentgate-dataset-template.xlsx"'
            },
        )

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

    @api.post("/datasets/import/excel", status_code=201)
    async def import_dataset_excel(
        file: UploadFile = File(...),
        name: str = Form(...),
        description: str = Form(""),
    ):
        try:
            if not file.filename or not file.filename.lower().endswith(".xlsx"):
                _raise_dataset_error(
                    _excel_upload_error("file must have a .xlsx filename"), 415
                )
            content = await file.read(MAX_EXCEL_UPLOAD_BYTES + 1)
            if len(content) > MAX_EXCEL_UPLOAD_BYTES:
                _raise_dataset_error(
                    _excel_upload_error("XLSX upload exceeds 10 MiB"), 413
                )
            dataset, version = await run_in_threadpool(
                datasets.import_excel, content, name, description
            )
            return {"dataset": dataset, "version": version}
        except ValueError as exc:
            _raise_dataset_error(exc)

    @api.get("/datasets/{dataset_id}/versions/{version}/export/excel")
    def export_dataset_excel(dataset_id: str, version: int):
        try:
            content = datasets.export_excel(dataset_id, version)
            dataset = datasets.get_dataset(dataset_id)
            dataset_version = datasets.get_version(dataset_id, version)
            return StreamingResponse(
                BytesIO(content),
                media_type=EXCEL_MEDIA_TYPE,
                headers={
                    "Content-Disposition": _excel_content_disposition(dataset.name, version),
                    "ETag": f'"{dataset_version.content_sha256}"',
                    "Cache-Control": "private, immutable",
                },
            )
        except DatasetExcelExportError as exc:
            _raise_dataset_error(exc)
        except ValueError as exc:
            _raise_dataset_error(exc, 404)

    @api.get("/evaluators")
    def evaluators():
        return service.evaluators()

    @api.post("/json-schema/validate", status_code=200)
    def validate_json_schema(request: ValidateSchemaRequest):
        schema = request.json_schema
        if isinstance(schema, str):
            try:
                schema = json.loads(schema)
            except json.JSONDecodeError as exc:
                return {"valid": False, "errors": [{
                    "code": "input_parse_error",
                    "message": f"JSON 解析失败：{exc.msg}",
                }]}
        return service.validate_json_schema(schema, request.instance_mode)

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
        except (ValueError, TargetIntegrationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @api.post("/evaluations/http", status_code=201)
    def launch_http(request: LaunchHttpRequest):
        try:
            return service.launch_http(
                TargetRef(
                    platform_id=request.platform_id,
                    target_type=TargetType.AGENT,
                    external_target_id=request.target_id,
                    external_version_id=request.version_id,
                ),
                endpoint=request.endpoint,
                credential_ref=request.credential_ref or None,
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                evaluator_ids=request.evaluator_ids,
                timeout_seconds=request.timeout_seconds,
            )
        except (ValueError, TargetIntegrationError) as exc:
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
        except (ValueError, TargetIntegrationError) as exc:
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

    @app.post("/v1/traces", status_code=200)
    async def receive_otlp(request: Request):
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        limits = OtlpIngestionLimits(
            max_request_bytes=int(os.getenv(
                "AGENTGATE_OTLP_MAX_REQUEST_BYTES", str(4 * 1024 * 1024)
            )),
            max_decompressed_bytes=int(os.getenv(
                "AGENTGATE_OTLP_MAX_DECOMPRESSED_BYTES", str(8 * 1024 * 1024)
            )),
        )
        if len(body) > limits.max_request_bytes:
            raise HTTPException(status_code=413, detail="OTLP request body is too large")
        content_encoding = request.headers.get("content-encoding", "")
        if content_encoding.strip().lower() not in ("", "identity", "gzip"):
            raise HTTPException(status_code=415, detail="unsupported Content-Encoding")
        try:
            body = decode_content_encoding(
                body, content_encoding, limits
            )
            if "application/x-protobuf" in content_type:
                report = ingest_otlp_http_protobuf(body, repository, limits)
                return Response(
                    encode_otlp_http_protobuf_response(report),
                    status_code=200,
                    media_type="application/x-protobuf",
                )
            if "json" not in content_type:
                raise HTTPException(status_code=415, detail="unsupported OTLP content type")
            report = ingest_otlp_http_json(json.loads(body), repository, limits)
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return report

    app.include_router(api)
    app.include_router(create_dataset_generation_router(
        generation,
        target_catalog,
        credential_store,
        getattr(active_generation_model, "validate_credential", None),
    ))
    app.state.repository = repository
    app.state.service = service
    app.state.dataset_generation_service = generation
    app.state.generation_credential_store = credential_store
    return app


app = create_app()
