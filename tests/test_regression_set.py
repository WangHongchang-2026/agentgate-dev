from datetime import UTC, datetime

import pytest

from agentgate.case import DatasetService
from agentgate.control_plane import EvaluationService
from agentgate.domain import (
    Case,
    CaseProvenance,
    CaseTurn,
    Dataset,
    DatasetPurpose,
    DatasetVersion,
    DatasetVersionStatus,
)
from agentgate.domain.base import content_sha256
from agentgate.storage.sqlite import SQLiteRepository


def old_case_payload() -> dict:
    return {
        "id": "old-case",
        "name": "Old case",
        "turns": [{"id": "old-turn", "input": {"message": "hello"}}],
    }


def test_old_dataset_and_case_payloads_default_to_standard_without_provenance():
    dataset = Dataset.model_validate({"id": "d", "name": "old"})
    case = Case.model_validate(old_case_payload())

    assert dataset.purpose == DatasetPurpose.STANDARD
    assert case.provenance is None


def test_regression_case_provenance_is_hashed_but_none_keeps_old_hash():
    old_case = Case.model_validate(old_case_payload())
    old_payload = {
        "dataset_id": "dataset",
        "cases": [old_case.model_dump(mode="json", exclude={"provenance"})],
        "notes": "",
    }
    old_version_payload = {
        "dataset_id": "dataset",
        "status": DatasetVersionStatus.PUBLISHED,
        "version": 1,
        "published_at": datetime(2026, 8, 20, tzinfo=UTC),
        "cases": old_payload["cases"],
        "notes": "",
        "content_sha256": content_sha256(old_payload),
    }
    restored = DatasetVersion.model_validate(old_version_payload)

    sourced = old_case.model_copy(update={
        "provenance": CaseProvenance(
            source_run_id="run-1",
            source_dataset_id="source-dataset",
            source_dataset_version=3,
            source_case_id=old_case.id,
            captured_at=datetime(2026, 8, 20, tzinfo=UTC),
            reason="high risk",
        ),
    })
    sourced_version = DatasetVersion(
        dataset_id="dataset",
        status=DatasetVersionStatus.PUBLISHED,
        version=1,
        published_at=datetime(2026, 8, 20, tzinfo=UTC),
        cases=(sourced,),
    )

    assert restored.content_sha256 == old_version_payload["content_sha256"]
    assert sourced_version.content_sha256 != restored.content_sha256


def test_case_provenance_is_immutable():
    provenance = CaseProvenance(
        source_run_id="run-1",
        source_dataset_id="dataset-1",
        source_dataset_version=1,
        source_case_id="case-1",
        captured_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    with pytest.raises((TypeError, ValueError)):
        provenance.reason = "changed"


def test_dataset_creation_accepts_regression_purpose_and_copy_preserves_it(tmp_path):
    service = DatasetService(SQLiteRepository(tmp_path / "regression.db"))
    source = service.create_dataset("Source", purpose=DatasetPurpose.REGRESSION)
    service.create_draft(source.id)
    source_case = Case(
        id="source-case",
        name="Source case",
        turns=(CaseTurn(id="source-turn", input={"message": "hello"}),),
        provenance=CaseProvenance(
            source_run_id="run-1",
            source_dataset_id="source-dataset",
            source_dataset_version=1,
            source_case_id="original-case",
            captured_at=datetime(2026, 8, 20, tzinfo=UTC),
        ),
    )
    service.save_case(source.id, source_case)
    service.publish_draft(source.id)

    copied, draft = service.copy_dataset(source.id, "Copied")

    assert copied.purpose == DatasetPurpose.REGRESSION
    assert draft.cases[0].provenance == source_case.provenance


def test_repository_saves_regression_dataset_and_draft_atomically(tmp_path):
    repository = SQLiteRepository(tmp_path / "atomic.db")
    dataset = Dataset(name="Regressions", purpose=DatasetPurpose.REGRESSION)
    draft = DatasetVersion(dataset_id=dataset.id, dataset_name=dataset.name)

    repository.save_dataset_with_draft(dataset, draft)

    assert repository.get_dataset(dataset.id) == dataset
    assert repository.get_dataset_draft(dataset.id) == draft


def test_add_case_to_new_regression_dataset_uses_run_snapshot(tmp_path):
    repository = SQLiteRepository(tmp_path / "membership.db")
    service = EvaluationService(repository)
    run = service.launch("loan-agent-v1-risky")
    source = run.snapshot.dataset.cases[0]

    dataset, draft, copied = service.add_case_to_regression_dataset(
        run_id=run.id,
        case_id=source.id,
        regression_dataset_id=None,
        new_dataset_name="Loan regressions",
        reason="direct approval",
    )

    assert dataset.purpose == DatasetPurpose.REGRESSION
    assert draft.cases == (copied,)
    assert copied.id != source.id
    assert copied.model_copy(update={"id": source.id, "provenance": None}) == source
    assert copied.provenance is not None
    assert copied.provenance.source_run_id == run.id
    assert copied.provenance.source_dataset_id == run.snapshot.dataset.dataset_id
    assert copied.provenance.source_dataset_version == run.snapshot.dataset.version
    assert copied.provenance.source_case_id == source.id
    assert copied.provenance.reason == "direct approval"


def test_regression_dataset_rejects_duplicate_source_case(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "duplicate.db"))
    run = service.launch("loan-agent-v1-risky")
    case_id = run.snapshot.dataset.cases[0].id
    dataset, _, _ = service.add_case_to_regression_dataset(
        run_id=run.id,
        case_id=case_id,
        regression_dataset_id=None,
        new_dataset_name="Regressions",
    )

    with pytest.raises(ValueError, match="already exists"):
        service.add_case_to_regression_dataset(
            run_id=run.id,
            case_id=case_id,
            regression_dataset_id=dataset.id,
            new_dataset_name=None,
        )


def test_existing_published_regression_dataset_gets_new_draft_and_runs_normally(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "published.db"))
    first_run = service.launch("loan-agent-v1-risky")
    first_case = first_run.snapshot.dataset.cases[0]
    dataset, _, _ = service.add_case_to_regression_dataset(
        run_id=first_run.id,
        case_id=first_case.id,
        regression_dataset_id=None,
        new_dataset_name="Regressions",
    )
    published = service.dataset_service.publish_draft(dataset.id)

    regression_run = service.launch(
        "loan-agent-v2-fixed", dataset.id, published.version,
    )

    assert regression_run.snapshot.dataset.dataset_id == dataset.id
    assert len(regression_run.snapshot.dataset.cases) == 1


def test_regression_membership_rejects_standard_dataset(tmp_path):
    service = EvaluationService(SQLiteRepository(tmp_path / "standard.db"))
    run = service.launch("loan-agent-v1-risky")
    standard = service.dataset_service.create_dataset("Standard")
    service.dataset_service.create_draft(standard.id)

    with pytest.raises(ValueError, match="regression Dataset"):
        service.add_case_to_regression_dataset(
            run_id=run.id,
            case_id=run.snapshot.dataset.cases[0].id,
            regression_dataset_id=standard.id,
            new_dataset_name=None,
        )
