"""Dataset/Case/version workflows shared by HTTP and CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agentgate.domain import Case, Dataset, DatasetVersion
from agentgate.storage.base import AgentGateRepository

from .import_export import DatasetExport, build_export, parse_export
from .validation import validate_dataset_version


def utcnow() -> datetime:
    return datetime.now(UTC)


class DatasetService:
    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def seed(self, dataset: Dataset, version: DatasetVersion) -> None:
        if self.repository.get_dataset(dataset.id) is None:
            self.repository.save_dataset(dataset)
        if self.repository.get_dataset_version(dataset.id, version.version or 0) is None:
            self.repository.save_dataset_version(version)

    def list_datasets(self, include_archived: bool = False) -> list[Dataset]:
        return self.repository.list_datasets(include_archived=include_archived)

    def get_dataset(self, dataset_id: str) -> Dataset:
        dataset = self.repository.get_dataset(dataset_id)
        if dataset is None:
            raise ValueError(f"unknown dataset: {dataset_id}")
        return dataset

    def create_dataset(self, name: str, description: str = "") -> Dataset:
        if not name.strip():
            raise ValueError("dataset name is required")
        dataset = Dataset(name=name.strip(), description=description.strip())
        self.repository.save_dataset(dataset)
        return dataset

    def update_dataset(
        self, dataset_id: str, *, name: str | None = None,
        description: str | None = None, archived: bool | None = None,
    ) -> Dataset:
        dataset = self.get_dataset(dataset_id)
        updates = {"updated_at": utcnow()}
        if name is not None:
            if not name.strip():
                raise ValueError("dataset name is required")
            updates["name"] = name.strip()
        if description is not None:
            updates["description"] = description.strip()
        if archived is not None:
            updates["archived"] = archived
        updated = dataset.model_copy(update=updates)
        self.repository.save_dataset(updated)
        return updated

    def archive_dataset(self, dataset_id: str) -> Dataset:
        return self.update_dataset(dataset_id, archived=True)

    def list_versions(self, dataset_id: str, include_draft: bool = True) -> list[DatasetVersion]:
        self.get_dataset(dataset_id)
        return self.repository.list_dataset_versions(dataset_id, include_draft=include_draft)

    def get_version(self, dataset_id: str, version: int) -> DatasetVersion:
        self.get_dataset(dataset_id)
        item = self.repository.get_dataset_version(dataset_id, version)
        if item is None:
            raise ValueError(f"unknown dataset version: {dataset_id} v{version}")
        return item

    def latest_published(self, dataset_id: str) -> DatasetVersion:
        self.get_dataset(dataset_id)
        version = self.repository.get_latest_dataset_version(dataset_id)
        if version is None:
            raise ValueError(f"dataset has no published version: {dataset_id}")
        return version

    def get_draft(self, dataset_id: str) -> DatasetVersion | None:
        self.get_dataset(dataset_id)
        return self.repository.get_dataset_draft(dataset_id)

    def create_draft(
        self, dataset_id: str, based_on_version: int | None = None
    ) -> DatasetVersion:
        dataset = self.get_dataset(dataset_id)
        if dataset.archived:
            raise ValueError("archived dataset cannot be edited")
        if self.repository.get_dataset_draft(dataset_id) is not None:
            raise ValueError("dataset already has an active draft")
        base = (
            self.get_version(dataset_id, based_on_version)
            if based_on_version is not None
            else self.repository.get_latest_dataset_version(dataset_id)
        )
        draft = DatasetVersion(
            dataset_id=dataset_id,
            dataset_name=dataset.name,
            dataset_description=dataset.description,
            based_on_version=base.version if base else None,
            cases=base.cases if base else (),
            notes=base.notes if base else "",
        )
        self.repository.save_dataset_version(draft)
        return draft

    def discard_draft(self, dataset_id: str) -> None:
        self.get_dataset(dataset_id)
        self.repository.delete_dataset_draft(dataset_id)

    def _draft(self, dataset_id: str) -> DatasetVersion:
        draft = self.get_draft(dataset_id)
        if draft is None:
            raise ValueError("dataset has no active draft")
        return draft

    def save_case(self, dataset_id: str, case: Case) -> DatasetVersion:
        draft = self._draft(dataset_id)
        cases = list(draft.cases)
        index = next((i for i, item in enumerate(cases) if item.id == case.id), None)
        if index is None:
            cases.append(case)
        else:
            cases[index] = case
        updated = DatasetVersion.model_validate({
            **draft.model_dump(mode="json"),
            "cases": cases,
            "updated_at": utcnow(),
            "content_sha256": "",
        })
        self.repository.save_dataset_version(updated)
        return updated

    def remove_case(self, dataset_id: str, case_id: str) -> DatasetVersion:
        draft = self._draft(dataset_id)
        cases = tuple(item for item in draft.cases if item.id != case_id)
        if len(cases) == len(draft.cases):
            raise ValueError(f"unknown case: {case_id}")
        updated = DatasetVersion.model_validate({
            **draft.model_dump(mode="json"),
            "cases": cases,
            "updated_at": utcnow(),
            "content_sha256": "",
        })
        self.repository.save_dataset_version(updated)
        return updated

    def copy_case(self, dataset_id: str, case_id: str) -> DatasetVersion:
        draft = self._draft(dataset_id)
        source = next((item for item in draft.cases if item.id == case_id), None)
        if source is None:
            raise ValueError(f"unknown case: {case_id}")
        copied = source.model_copy(update={"id": str(uuid4()), "name": f"{source.name}（副本）"})
        return self.save_case(dataset_id, copied)

    def reorder_cases(self, dataset_id: str, case_ids: list[str]) -> DatasetVersion:
        draft = self._draft(dataset_id)
        by_id = {item.id: item for item in draft.cases}
        if len(case_ids) != len(set(case_ids)) or set(case_ids) != set(by_id):
            raise ValueError("case order must contain every draft Case exactly once")
        updated = DatasetVersion.model_validate({
            **draft.model_dump(mode="json"),
            "cases": [by_id[item] for item in case_ids],
            "updated_at": utcnow(),
            "content_sha256": "",
        })
        self.repository.save_dataset_version(updated)
        return updated

    def publish_draft(self, dataset_id: str) -> DatasetVersion:
        draft = self._draft(dataset_id)
        validate_dataset_version(draft)
        return self.repository.publish_dataset_draft(dataset_id, utcnow())

    def copy_dataset(
        self, source_dataset_id: str, name: str, source_version: int | None = None
    ) -> tuple[Dataset, DatasetVersion]:
        source = (
            self.get_version(source_dataset_id, source_version)
            if source_version is not None
            else self.latest_published(source_dataset_id)
        )
        dataset = self.create_dataset(name)
        draft = DatasetVersion(
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            dataset_description=dataset.description,
            cases=tuple(
                case.model_copy(update={"id": str(uuid4())}) for case in source.cases
            ),
            notes=f"Copied from {source_dataset_id} v{source.version}",
        )
        self.repository.save_dataset_version(draft)
        return dataset, draft

    def export_version(self, dataset_id: str, version: int) -> DatasetExport:
        return build_export(self.get_dataset(dataset_id), self.get_version(dataset_id, version))

    def import_dataset(self, payload: dict | str) -> tuple[Dataset, DatasetVersion]:
        exported = parse_export(payload)
        if exported.dataset.id != exported.version.dataset_id:
            raise ValueError("imported Dataset and version identities do not match")
        if self.repository.get_dataset(exported.dataset.id) is not None:
            raise ValueError(f"dataset already exists: {exported.dataset.id}")
        validate_dataset_version(exported.version)
        self.repository.save_dataset(exported.dataset)
        self.repository.save_dataset_version(exported.version)
        return exported.dataset, exported.version
