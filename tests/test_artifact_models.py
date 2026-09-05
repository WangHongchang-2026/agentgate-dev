from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agentgate.domain import Artifact, ArtifactProducer


def artifact(**overrides: object) -> Artifact:
    values: dict[str, object] = {
        "id": "artifact-1",
        "run_id": "run-1",
        "case_id": "case-1",
        "trace_id": "trace-8",
        "producer": ArtifactProducer.AGENT,
        "producer_name": "loan-report-agent",
        "artifact_type": "document",
        "filename": "loan-report.pdf",
        "media_type": "application/pdf",
        "storage_uri": "s3://agentgate/run-1/loan-report.pdf",
        "sha256": "a" * 64,
        "size_bytes": 284_102,
        "created_at": datetime(2026, 9, 5, tzinfo=UTC),
        "metadata": {"page_count": 4, "labels": ["loan", "report"]},
    }
    values.update(overrides)
    return Artifact(**values)


def test_artifact_records_execution_owner_and_storage_reference() -> None:
    value = artifact()

    assert value.run_id == "run-1"
    assert value.case_id == "case-1"
    assert value.trace_id == "trace-8"
    assert value.storage_uri.endswith("loan-report.pdf")


def test_artifact_metadata_is_recursively_immutable() -> None:
    value = artifact()

    assert value.metadata["labels"] == ("loan", "report")
    with pytest.raises(TypeError):
        value.metadata["page_count"] = 5  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("run_id", " "),
        ("case_id", ""),
        ("trace_id", "\t"),
        ("artifact_type", " "),
        ("filename", ""),
        ("media_type", " "),
        ("storage_uri", ""),
        ("producer_name", " "),
    ],
)
def test_artifact_rejects_blank_text(field: str, invalid: str) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        artifact(**{field: invalid})


@pytest.mark.parametrize("sha256", ["A" * 64, "a" * 63, "not-a-hash"])
def test_artifact_rejects_invalid_sha256(sha256: str) -> None:
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        artifact(sha256=sha256)


def test_artifact_rejects_negative_size() -> None:
    with pytest.raises(ValidationError):
        artifact(size_bytes=-1)


def test_artifact_normalizes_timestamp_to_utc() -> None:
    value = artifact(
        created_at=datetime(2026, 9, 5, 8, tzinfo=timezone(timedelta(hours=8)))
    )

    assert value.created_at == datetime(2026, 9, 5, tzinfo=UTC)


def test_artifact_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        artifact(created_at=datetime(2026, 9, 5))
