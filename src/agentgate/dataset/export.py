"""Export validated Dataset domain objects to external formats."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentgate.domain import Dataset, DatasetVersion

from .formats.json import FORMAT_NAME, FORMAT_VERSION, dump as dump_json


@dataclass(frozen=True, slots=True)
class ExportedDataset:
    """Encoded Dataset content and transport-neutral file metadata."""

    content: bytes
    media_type: str
    filename: str


def _safe_filename_stem(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return sanitized or "dataset"


def export_dataset(
    dataset: Dataset,
    version: DatasetVersion,
    format_name: str,
) -> ExportedDataset:
    """Encode one Dataset version without querying storage or building an HTTP response."""

    if dataset.id != version.dataset_id:
        raise ValueError("Dataset and DatasetVersion identities do not match")
    if format_name != "json":
        raise ValueError(f"unsupported Dataset output format: {format_name!r}")

    content = dump_json(
        {
            "format": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "dataset": dataset.model_dump(mode="json"),
            "version": version.model_dump(mode="json"),
        }
    )
    version_label = f"v{version.version}" if version.version is not None else "draft"
    return ExportedDataset(
        content=content,
        media_type="application/json",
        filename=f"{_safe_filename_stem(dataset.name)}-{version_label}.json",
    )

