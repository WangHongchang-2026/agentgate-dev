"""Lightweight OTLP/HTTP transport for external Agent traces."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from agentgate.server.dependencies import ServerDependencies, get_dependencies
from agentgate.server.errors import raise_unprocessable


MAX_REQUEST_BYTES = 4 * 1024 * 1024

router = APIRouter(tags=["telemetry"])
Dependencies = Annotated[ServerDependencies, Depends(get_dependencies)]


@router.post("/v1/traces", status_code=202)
async def receive_traces(
    request: Request, dependencies: Dependencies
) -> dict[str, int]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type.strip().lower() != "application/json":
        raise HTTPException(
            status_code=415,
            detail="OTLP receiver accepts application/json only",
        )

    body = await _read_bounded_body(request)
    try:
        payload = json.loads(body)
        accepted_spans = dependencies.ingest_otlp_json(payload)
    except (TypeError, ValueError, UnicodeDecodeError) as error:
        raise_unprocessable(error)
    return {"accepted_spans": accepted_spans}


async def _read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                _raise_too_large()
        except ValueError:
            raise HTTPException(
                status_code=400, detail="invalid Content-Length header"
            ) from None

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES:
            _raise_too_large()
    return bytes(body)


def _raise_too_large() -> None:
    raise HTTPException(
        status_code=413,
        detail="OTLP request body exceeds the 4 MiB limit",
    )
