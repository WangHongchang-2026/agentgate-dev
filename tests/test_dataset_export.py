from datetime import UTC, datetime

import pytest

from agentgate.dataset.export import ExportedDataset, export_dataset
from agentgate.dataset.loader import load_dataset
from agentgate.domain import Case, CaseTurn, Dataset, DatasetVersion


NOW = datetime(2026, 9, 6, tzinfo=UTC)


def dataset_and_version(
    *, dataset_name: str = "Loan Tests", version_number: int | None = None
) -> tuple[Dataset, DatasetVersion]:
    dataset = Dataset(
        id="dataset",
        name=dataset_name,
        created_at=NOW,
        updated_at=NOW,
    )
    case = Case(
        id="case",
        name="Case",
        turns=(CaseTurn(id="turn", input={"message": "申请贷款"}),),
    )
    version_values: dict[str, object] = {
        "id": "version",
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "cases": (case,),
        "created_at": NOW,
        "updated_at": NOW,
    }
    if version_number is not None:
        version_values.update(
            status="published",
            version=version_number,
            published_at=NOW,
        )
    return dataset, DatasetVersion.model_validate(version_values)


def test_export_json_returns_content_metadata_and_round_trips() -> None:
    dataset, version = dataset_and_version(version_number=3)

    exported = export_dataset(dataset, version, "json")
    loaded_dataset, loaded_version = load_dataset(exported.content, "json")

    assert exported == ExportedDataset(
        content=exported.content,
        media_type="application/json",
        filename="Loan-Tests-v3.json",
    )
    assert loaded_dataset == dataset
    assert loaded_version == version
    assert "申请贷款".encode() in exported.content


def test_export_uses_safe_fallback_and_draft_filenames() -> None:
    dataset, version = dataset_and_version(dataset_name="中文数据集")

    exported = export_dataset(dataset, version, "json")

    assert exported.filename == "dataset-draft.json"


def test_export_rejects_mismatched_identity() -> None:
    dataset, version = dataset_and_version()
    other = dataset.model_copy(update={"id": "other"})

    with pytest.raises(ValueError, match="identities do not match"):
        export_dataset(other, version, "json")


def test_export_rejects_unknown_format() -> None:
    dataset, version = dataset_and_version()

    with pytest.raises(ValueError, match="unsupported Dataset output format"):
        export_dataset(dataset, version, "yaml")
