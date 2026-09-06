"""Dataset catalog, version, Case, import, and export endpoints."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from agentgate.dataset.formats.xlsx import (
    MAX_INPUT_BYTES,
    SHEET_NAME,
    XlsxFormatError,
    XlsxIssue,
)
from agentgate.domain import Case, DatasetVersionStatus
from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_not_found, raise_unprocessable, raise_xlsx_error


router = APIRouter(prefix="/api/datasets", tags=["datasets"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


class CreateDatasetRequest(BaseModel):
    name: str
    description: str = ""


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


@router.post("/import", status_code=201)
def import_dataset(payload: dict[str, Any], dependencies: Dependencies):
    try:
        dataset, version = dependencies.datasets.import_json(payload)
    except ValueError as error:
        raise_unprocessable(error)
    return {"dataset": dataset, "version": version}


@router.post("/import/xlsx", status_code=201)
async def import_dataset_xlsx(
    dependencies: Dependencies,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise_xlsx_error(_xlsx_error("file must have a .xlsx filename"))

    try:
        content = await file.read(MAX_INPUT_BYTES + 1)
    finally:
        await file.close()
    if len(content) > MAX_INPUT_BYTES:
        raise_xlsx_error(_xlsx_error("file exceeds the 10 MiB limit"))

    try:
        dataset, version = await run_in_threadpool(
            dependencies.datasets.import_xlsx,
            content,
            name,
            description,
        )
    except XlsxFormatError as error:
        raise_xlsx_error(error)
    except ValueError as error:
        raise_unprocessable(error)
    return {"dataset": dataset, "version": version}


@router.get("")
def list_datasets(dependencies: Dependencies) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for dataset in dependencies.datasets.list_datasets():
        versions = dependencies.datasets.list_versions(dataset.id)
        latest = next(
            (
                item
                for item in versions
                if item.status is DatasetVersionStatus.PUBLISHED
            ),
            None,
        )
        summaries.append(
            {
                **dataset.model_dump(mode="json"),
                "version": latest.version if latest else None,
                "case_count": len(latest.cases) if latest else 0,
                "has_draft": any(
                    item.status is DatasetVersionStatus.DRAFT for item in versions
                ),
            }
        )
    return summaries


@router.post("", status_code=201)
def create_dataset(request: CreateDatasetRequest, dependencies: Dependencies):
    try:
        dataset = dependencies.datasets.create_dataset(
            request.name, request.description
        )
        draft = dependencies.datasets.create_draft(dataset.id)
    except ValueError as error:
        raise_unprocessable(error)
    return {"dataset": dataset, "draft": draft}


@router.get("/{dataset_id}")
def dataset_detail(dataset_id: str, dependencies: Dependencies):
    try:
        return {
            "dataset": dependencies.datasets.get_dataset(dataset_id),
            "versions": dependencies.datasets.list_versions(dataset_id),
        }
    except ValueError as error:
        raise_not_found(error)


@router.patch("/{dataset_id}")
def update_dataset(
    dataset_id: str,
    request: UpdateDatasetRequest,
    dependencies: Dependencies,
):
    try:
        return dependencies.datasets.update_dataset(
            dataset_id,
            name=request.name,
            description=request.description,
            archived=request.archived,
        )
    except ValueError as error:
        raise_unprocessable(error)


@router.delete("/{dataset_id}")
def archive_dataset(dataset_id: str, dependencies: Dependencies):
    try:
        return dependencies.datasets.archive_dataset(dataset_id)
    except ValueError as error:
        raise_not_found(error)


@router.post("/{dataset_id}/copy", status_code=201)
def copy_dataset(
    dataset_id: str,
    request: CopyDatasetRequest,
    dependencies: Dependencies,
):
    try:
        dataset, draft = dependencies.datasets.copy_dataset(
            dataset_id, request.name, request.source_version
        )
    except ValueError as error:
        raise_unprocessable(error)
    return {"dataset": dataset, "draft": draft}


@router.get("/{dataset_id}/versions")
def list_dataset_versions(dataset_id: str, dependencies: Dependencies):
    try:
        return dependencies.datasets.list_versions(dataset_id)
    except ValueError as error:
        raise_not_found(error)


@router.get("/{dataset_id}/versions/{version}")
def dataset_version(dataset_id: str, version: int, dependencies: Dependencies):
    try:
        return dependencies.datasets.get_version(dataset_id, version)
    except ValueError as error:
        raise_not_found(error)


@router.get("/{dataset_id}/versions/{version}/export")
def export_dataset_json(
    dataset_id: str, version: int, dependencies: Dependencies
):
    try:
        exported = dependencies.datasets.export_version(dataset_id, version, "json")
    except ValueError as error:
        raise_not_found(error)
    return json.loads(exported.content)


@router.get("/{dataset_id}/versions/{version}/export/xlsx")
def export_dataset_xlsx(
    dataset_id: str, version: int, dependencies: Dependencies
):
    try:
        exported = dependencies.datasets.export_version(dataset_id, version, "xlsx")
        dataset_version = dependencies.datasets.get_version(dataset_id, version)
    except XlsxFormatError as error:
        raise_xlsx_error(error)
    except ValueError as error:
        raise_not_found(error)
    return StreamingResponse(
        BytesIO(exported.content),
        media_type=exported.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{exported.filename}"',
            "ETag": f'"{dataset_version.content_sha256}"',
            "Cache-Control": "private, immutable",
        },
    )


@router.get("/{dataset_id}/drafts/current")
def current_draft(dataset_id: str, dependencies: Dependencies):
    try:
        draft = dependencies.datasets.get_draft(dataset_id)
    except ValueError as error:
        raise_not_found(error)
    if draft is None:
        raise HTTPException(status_code=404, detail="Dataset has no active draft")
    return draft


@router.post("/{dataset_id}/drafts", status_code=201)
def create_draft(
    dataset_id: str,
    request: CreateDraftRequest,
    dependencies: Dependencies,
):
    try:
        return dependencies.datasets.create_draft(
            dataset_id, request.based_on_version
        )
    except ValueError as error:
        raise_unprocessable(error)


@router.delete("/{dataset_id}/drafts/current", status_code=204)
def discard_draft(dataset_id: str, dependencies: Dependencies) -> None:
    try:
        dependencies.datasets.discard_draft(dataset_id)
    except ValueError as error:
        raise_not_found(error)


@router.post("/{dataset_id}/drafts/publish")
def publish_draft(dataset_id: str, dependencies: Dependencies):
    try:
        return dependencies.datasets.publish_draft(dataset_id)
    except ValueError as error:
        raise_unprocessable(error)


@router.post("/{dataset_id}/drafts/cases", status_code=201)
def add_case(dataset_id: str, case: Case, dependencies: Dependencies):
    try:
        return dependencies.datasets.save_case(dataset_id, case)
    except ValueError as error:
        raise_unprocessable(error)


@router.put("/{dataset_id}/drafts/cases/{case_id}")
def update_case(
    dataset_id: str,
    case_id: str,
    case: Case,
    dependencies: Dependencies,
):
    if case.id != case_id:
        raise HTTPException(status_code=422, detail="Case ID cannot be changed")
    try:
        return dependencies.datasets.save_case(dataset_id, case)
    except ValueError as error:
        raise_unprocessable(error)


@router.delete("/{dataset_id}/drafts/cases/{case_id}")
def delete_case(dataset_id: str, case_id: str, dependencies: Dependencies):
    try:
        return dependencies.datasets.remove_case(dataset_id, case_id)
    except ValueError as error:
        raise_not_found(error)


@router.post("/{dataset_id}/drafts/cases/{case_id}/copy")
def copy_case(dataset_id: str, case_id: str, dependencies: Dependencies):
    try:
        return dependencies.datasets.copy_case(dataset_id, case_id)
    except ValueError as error:
        raise_not_found(error)


@router.put("/{dataset_id}/drafts/case-order")
def reorder_cases(
    dataset_id: str,
    request: ReorderCasesRequest,
    dependencies: Dependencies,
):
    try:
        return dependencies.datasets.reorder_cases(dataset_id, request.case_ids)
    except ValueError as error:
        raise_unprocessable(error)


def _xlsx_error(message: str) -> XlsxFormatError:
    return XlsxFormatError((XlsxIssue(SHEET_NAME, None, None, message),))
