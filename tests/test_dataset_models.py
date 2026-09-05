from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agentgate.domain import (
    Case,
    CaseTurn,
    Dataset,
    DatasetVersion,
    DatasetVersionStatus,
)


def _case(case_id: str = "case") -> Case:
    return Case(
        id=case_id,
        name=case_id,
        turns=(CaseTurn(id=f"{case_id}-turn", input={"message": "hello"}),),
    )


def test_dataset_rejects_blank_identity_and_invalid_timestamp_order():
    now = datetime.now(UTC)

    with pytest.raises(ValidationError):
        Dataset(id=" ", name="dataset")
    with pytest.raises(ValidationError):
        Dataset(name=" ")
    with pytest.raises(ValidationError, match="must not precede"):
        Dataset(name="dataset", created_at=now, updated_at=now - timedelta(seconds=1))


def test_dataset_timestamps_require_timezone_and_are_normalized_to_utc():
    with pytest.raises(ValidationError, match="timezone-aware"):
        Dataset(name="dataset", created_at=datetime(2026, 1, 1))

    offset = timezone(timedelta(hours=8))
    dataset = Dataset(
        name="dataset",
        created_at=datetime(2026, 1, 1, 8, tzinfo=offset),
        updated_at=datetime(2026, 1, 1, 9, tzinfo=offset),
    )
    assert dataset.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert dataset.created_at.tzinfo is UTC


def test_published_version_requires_complete_publication_fields_and_cases():
    now = datetime.now(UTC)

    with pytest.raises(ValidationError):
        DatasetVersion(
            dataset_id="dataset",
            status=DatasetVersionStatus.PUBLISHED,
            created_at=now,
            updated_at=now,
        )

    version = DatasetVersion(
        dataset_id="dataset",
        version=1,
        status=DatasetVersionStatus.PUBLISHED,
        cases=(_case(),),
        created_at=now,
        updated_at=now,
        published_at=now,
    )
    assert version.content_sha256


def test_dataset_version_rejects_duplicate_case_ids_and_invalid_ancestry():
    with pytest.raises(ValidationError, match="Case ids must be unique"):
        DatasetVersion(dataset_id="dataset", cases=(_case(), _case()))

    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="based_on_version must precede"):
        DatasetVersion(
            dataset_id="dataset",
            version=2,
            based_on_version=2,
            status=DatasetVersionStatus.PUBLISHED,
            cases=(_case(),),
            created_at=now,
            updated_at=now,
            published_at=now,
        )


def test_content_hash_tracks_ordered_case_content_but_not_operational_metadata():
    first = _case("first")
    second = _case("second")
    baseline = DatasetVersion(dataset_id="dataset", cases=(first, second), notes="note")

    metadata_change = DatasetVersion(
        dataset_id="dataset",
        dataset_name="renamed",
        dataset_description="changed",
        based_on_version=3,
        cases=(first, second),
        notes="note",
    )
    reordered = DatasetVersion(
        dataset_id="dataset", cases=(second, first), notes="note"
    )

    assert metadata_change.content_sha256 == baseline.content_sha256
    assert reordered.content_sha256 != baseline.content_sha256
