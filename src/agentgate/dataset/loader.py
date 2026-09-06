"""Load external Dataset documents into validated domain objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentgate.domain import Dataset, DatasetVersion

from .formats.json import parse as parse_json


def load_dataset(
    source: str | bytes | Mapping[str, Any],
    format_name: str,
) -> tuple[Dataset, DatasetVersion]:
    """Load one supported external document without persisting it."""

    if format_name != "json":
        raise ValueError(f"unsupported Dataset input format: {format_name!r}")

    document = parse_json(source)
    dataset = Dataset.model_validate(document["dataset"])
    version = DatasetVersion.model_validate(document["version"])
    if dataset.id != version.dataset_id:
        raise ValueError("Dataset and DatasetVersion identities do not match")
    return dataset, version

