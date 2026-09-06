"""User-facing Dataset, version, Case, and exchange workflows."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from agentgate.dataset.export import ExportedDataset, export_dataset
from agentgate.dataset.loader import load_cases, load_dataset
from agentgate.dataset.versioning import (
    copy_case as copy_draft_case,
    create_draft as build_draft,
    publish_draft as build_publication,
    remove_case as remove_draft_case,
    reorder_cases as reorder_draft_cases,
    with_case,
)
from agentgate.domain import Case, Dataset, DatasetVersion, utcnow
from agentgate.storage.repository import AgentGateRepository


class DatasetManagement:
    """Coordinate Dataset workflows across domain mechanics and persistence."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def list_datasets(self, include_archived: bool = False) -> list[Dataset]:
        return self.repository.list_datasets(include_archived=include_archived)

    def get_dataset(self, dataset_id: str) -> Dataset:
        dataset = self.repository.get_dataset(dataset_id)
        if dataset is None:
            raise ValueError(f"unknown Dataset: {dataset_id}")
        return dataset

    def create_dataset(self, name: str, description: str = "") -> Dataset:
        dataset = Dataset(name=name.strip(), description=description.strip())
        self.repository.save_dataset(dataset)
        return dataset

    def update_dataset(
        self,
        dataset_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        archived: bool | None = None,
    ) -> Dataset:
        dataset = self.get_dataset(dataset_id)
        changes: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            changes["name"] = name.strip()
        if description is not None:
            changes["description"] = description.strip()
        if archived is not None:
            changes["archived"] = archived
        updated = Dataset.model_validate(
            {**dataset.model_dump(mode="json"), **changes}
        )
        self.repository.save_dataset(updated)
        return updated

    def archive_dataset(self, dataset_id: str) -> Dataset:
        return self.update_dataset(dataset_id, archived=True)

    def list_versions(
        self, dataset_id: str, include_draft: bool = True
    ) -> list[DatasetVersion]:
        self.get_dataset(dataset_id)
        return self.repository.list_dataset_versions(
            dataset_id, include_draft=include_draft
        )

    def get_version(self, dataset_id: str, version: int) -> DatasetVersion:
        self.get_dataset(dataset_id)
        item = self.repository.get_published_dataset_version(dataset_id, version)
        if item is None:
            raise ValueError(f"unknown Dataset version: {dataset_id} v{version}")
        return item

    def latest_published(self, dataset_id: str) -> DatasetVersion:
        self.get_dataset(dataset_id)
        version = self.repository.get_latest_published_dataset_version(dataset_id)
        if version is None:
            raise ValueError(f"Dataset has no published version: {dataset_id}")
        return version

    def get_draft(self, dataset_id: str) -> DatasetVersion | None:
        self.get_dataset(dataset_id)
        return self.repository.get_dataset_draft(dataset_id)

    def create_draft(
        self, dataset_id: str, based_on_version: int | None = None
    ) -> DatasetVersion:
        dataset = self.get_dataset(dataset_id)
        if dataset.archived:
            raise ValueError("archived Dataset cannot be edited")
        if self.repository.get_dataset_draft(dataset_id) is not None:
            raise ValueError("Dataset already has an active draft")
        base = (
            self.get_version(dataset_id, based_on_version)
            if based_on_version is not None
            else self.repository.get_latest_published_dataset_version(dataset_id)
        )
        draft = build_draft(dataset, base, str(uuid4()), utcnow())
        self.repository.save_dataset_version(draft)
        return draft

    def discard_draft(self, dataset_id: str) -> None:
        draft = self._draft(dataset_id)
        self.repository.delete_dataset_draft(dataset_id, draft.id)

    def _draft(self, dataset_id: str) -> DatasetVersion:
        draft = self.get_draft(dataset_id)
        if draft is None:
            raise ValueError("Dataset has no active draft")
        return draft

    def save_case(self, dataset_id: str, case: Case) -> DatasetVersion:
        updated = with_case(self._draft(dataset_id), case, utcnow())
        self.repository.save_dataset_version(updated)
        return updated

    def remove_case(self, dataset_id: str, case_id: str) -> DatasetVersion:
        updated = remove_draft_case(self._draft(dataset_id), case_id, utcnow())
        self.repository.save_dataset_version(updated)
        return updated

    def copy_case(self, dataset_id: str, case_id: str) -> DatasetVersion:
        draft = self._draft(dataset_id)
        source = next((case for case in draft.cases if case.id == case_id), None)
        if source is None:
            raise ValueError(f"unknown Case: {case_id}")
        updated = copy_draft_case(
            draft,
            case_id,
            new_case_id=str(uuid4()),
            new_name=f"{source.name}（副本）",
            updated_at=utcnow(),
        )
        self.repository.save_dataset_version(updated)
        return updated

    def reorder_cases(
        self, dataset_id: str, case_ids: list[str]
    ) -> DatasetVersion:
        updated = reorder_draft_cases(self._draft(dataset_id), case_ids, utcnow())
        self.repository.save_dataset_version(updated)
        return updated

    def publish_draft(self, dataset_id: str) -> DatasetVersion:
        draft = self._draft(dataset_id)
        latest = self.repository.get_latest_published_dataset_version(dataset_id)
        next_version = (latest.version if latest and latest.version else 0) + 1
        published = build_publication(
            draft,
            publication_id=str(uuid4()),
            version=next_version,
            published_at=utcnow(),
        )
        self.repository.replace_dataset_draft(draft.id, published)
        return published

    def copy_dataset(
        self,
        source_dataset_id: str,
        name: str,
        source_version: int | None = None,
    ) -> tuple[Dataset, DatasetVersion]:
        source = (
            self.get_version(source_dataset_id, source_version)
            if source_version is not None
            else self.latest_published(source_dataset_id)
        )
        dataset = Dataset(name=name.strip())
        draft = DatasetVersion(
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            dataset_description=dataset.description,
            cases=tuple(
                case.model_copy(update={"id": str(uuid4())})
                for case in source.cases
            ),
            notes=f"Copied from {source_dataset_id} v{source.version}",
        )
        self.repository.save_dataset_with_version(dataset, draft)
        return dataset, draft

    def import_json(
        self, source: str | bytes | Mapping[str, Any]
    ) -> tuple[Dataset, DatasetVersion]:
        dataset, version = load_dataset(source, "json")
        if self.repository.get_dataset(dataset.id) is not None:
            raise ValueError(f"Dataset already exists: {dataset.id}")
        self.repository.save_dataset_with_version(dataset, version)
        return dataset, version

    def import_xlsx(
        self, source: bytes, name: str, description: str = ""
    ) -> tuple[Dataset, DatasetVersion]:
        cases = load_cases(source, "xlsx")
        dataset = Dataset(name=name.strip(), description=description.strip())
        draft = DatasetVersion(
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            dataset_description=dataset.description,
            cases=cases,
        )
        self.repository.save_dataset_with_version(dataset, draft)
        return dataset, draft

    def export_version(
        self, dataset_id: str, version: int, format_name: str
    ) -> ExportedDataset:
        dataset = self.get_dataset(dataset_id)
        published = self.get_version(dataset_id, version)
        return export_dataset(dataset, published, format_name)

