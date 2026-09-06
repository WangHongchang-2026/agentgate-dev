"""Load external Dataset documents into validated domain objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter

from agentgate.domain import Case, Dataset, DatasetVersion

from .formats.json import parse as parse_json
from .formats.xlsx import parse as parse_xlsx


_CASES = TypeAdapter(tuple[Case, ...])


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


def load_cases(source: bytes, format_name: str) -> tuple[Case, ...]:
    """Load Case objects from a supported collection-only format."""

    if format_name != "xlsx":
        raise ValueError(f"unsupported Case input format: {format_name!r}")
    return _CASES.validate_python(parse_xlsx(source))
